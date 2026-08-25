"""Inspect and checksum ForgeOS Python release distributions."""

import argparse
import hashlib
import json
import re
import tarfile
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from typing import Iterable

from .release import PACKAGE_VERSION

TAG_PREFIX = "forgeos-v"
PROJECT_NAME = "forgeos-harness"
NORMALIZED_NAME = "forgeos_harness"
REQUIRED_LICENSE_FILES = ("LICENSE", "NOTICE")
REQUIRED_PACKAGE_FILES = (
    "forgeos/release_manifest.json",
    "forgeos/protocol_fixtures/v1/protocol.json",
    "forgeos/web/index.html",
    "forgeos/web/app.js",
    "forgeos/web/operator.js",
    "forgeos/web/pilot.js",
    "forgeos/web/styles.css",
)


@dataclass(frozen=True, slots=True)
class ReleaseArtifact:
    name: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class DistributionReport:
    package: str
    version: str
    tag: str | None
    artifacts: tuple[ReleaseArtifact, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "package": self.package,
            "version": self.version,
            "tag": self.tag,
            "passed": True,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }


def inspect_distribution(
    project_root: Path,
    dist_dir: Path,
    *,
    tag: str | None = None,
) -> DistributionReport:
    """Validate source metadata and the single wheel/sdist release pair."""

    project_version = _read_project_version(project_root / "pyproject.toml")
    manifest = json.loads(
        (project_root / "src" / "forgeos" / "release_manifest.json").read_text(encoding="utf-8")
    )
    versions = {project_version, PACKAGE_VERSION, str(manifest.get("package_version", ""))}
    if versions != {PACKAGE_VERSION}:
        raise ValueError(f"package version mismatch: {sorted(versions)}")
    if tag is not None and tag != f"{TAG_PREFIX}{PACKAGE_VERSION}":
        raise ValueError(f"release tag must be {TAG_PREFIX}{PACKAGE_VERSION}, got {tag}")

    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("dist must contain exactly one wheel and one source distribution")

    _inspect_wheel(wheels[0])
    _inspect_sdist(sdists[0])
    artifacts = tuple(_artifact(path) for path in sorted((*wheels, *sdists)))
    return DistributionReport(PROJECT_NAME, PACKAGE_VERSION, tag, artifacts)


def write_checksums(report: DistributionReport, destination: Path) -> None:
    lines = [f"{artifact.sha256}  {artifact.name}" for artifact in report.artifacts]
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _read_project_version(path: Path) -> str:
    section = ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if section == "project" and line.startswith("version"):
            key, separator, value = line.partition("=")
            if key.strip() == "version" and separator:
                return str(json.loads(value.strip()))
    raise ValueError("pyproject.toml is missing [project].version")


def _inspect_wheel(path: Path) -> None:
    expected = f"{NORMALIZED_NAME}-{PACKAGE_VERSION}-py3-none-any.whl"
    if path.name != expected:
        raise ValueError(f"unexpected wheel filename: {path.name}; expected {expected}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        missing = [name for name in REQUIRED_PACKAGE_FILES if name not in names]
        if missing:
            raise ValueError(f"wheel is missing package files: {', '.join(missing)}")
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ValueError("wheel must contain exactly one METADATA file")
        metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        if metadata["Name"] != PROJECT_NAME or metadata["Version"] != PACKAGE_VERSION:
            raise ValueError("wheel metadata name/version does not match release")
        _require_license_names(names)


def _inspect_sdist(path: Path) -> None:
    expected = f"{NORMALIZED_NAME}-{PACKAGE_VERSION}.tar.gz"
    if path.name != expected:
        raise ValueError(f"unexpected sdist filename: {path.name}; expected {expected}")
    prefix = f"{NORMALIZED_NAME}-{PACKAGE_VERSION}/"
    with tarfile.open(path, "r:gz") as archive:
        names = set(archive.getnames())
    for license_name in REQUIRED_LICENSE_FILES:
        if f"{prefix}{license_name}" not in names:
            raise ValueError(f"source distribution is missing {license_name}")


def _require_license_names(names: Iterable[str]) -> None:
    for license_name in REQUIRED_LICENSE_FILES:
        pattern = re.compile(rf"\.dist-info/licenses/{re.escape(license_name)}$")
        if not any(pattern.search(name) for name in names):
            raise ValueError(f"wheel is missing dist-info/licenses/{license_name}")


def _artifact(path: Path) -> ReleaseArtifact:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return ReleaseArtifact(path.name, path.stat().st_size, digest.hexdigest())


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--tag")
    parser.add_argument("--write-checksums", action="store_true")
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    dist_dir = args.dist.resolve()
    report = inspect_distribution(project_root, dist_dir, tag=args.tag)
    if args.write_checksums:
        write_checksums(report, dist_dir / "SHA256SUMS")
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
