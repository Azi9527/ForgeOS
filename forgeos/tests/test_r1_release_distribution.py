import hashlib
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from forgeos.release_artifacts import (
    PACKAGE_VERSION,
    DistributionReport,
    ReleaseArtifact,
    inspect_distribution,
    write_checksums,
)


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "src/forgeos").mkdir(parents=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "forgeos-harness"\nversion = "{PACKAGE_VERSION}"\n',
        encoding="utf-8",
    )
    (root / "src/forgeos/release_manifest.json").write_text(
        json.dumps({"package_version": PACKAGE_VERSION}),
        encoding="utf-8",
    )
    return root


def _distributions(root: Path) -> Path:
    dist = root / "dist"
    dist.mkdir()
    wheel = dist / f"forgeos_harness-{PACKAGE_VERSION}-py3-none-any.whl"
    dist_info = f"forgeos_harness-{PACKAGE_VERSION}.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in (
            "forgeos/release_manifest.json",
            "forgeos/protocol_fixtures/v1/protocol.json",
            "forgeos/web/index.html",
            "forgeos/web/app.js",
            "forgeos/web/operator.js",
            "forgeos/web/styles.css",
        ):
            archive.writestr(name, b"{}")
        archive.writestr(
            f"{dist_info}/METADATA",
            f"Name: forgeos-harness\nVersion: {PACKAGE_VERSION}\n",
        )
        archive.writestr(f"{dist_info}/licenses/LICENSE", "Apache-2.0")
        archive.writestr(f"{dist_info}/licenses/NOTICE", "notice")
    sdist = dist / f"forgeos_harness-{PACKAGE_VERSION}.tar.gz"
    source = root / "LICENSE"
    source.write_text("Apache-2.0", encoding="utf-8")
    notice = root / "NOTICE"
    notice.write_text("notice", encoding="utf-8")
    prefix = f"forgeos_harness-{PACKAGE_VERSION}"
    with tarfile.open(sdist, "w:gz") as archive:
        archive.add(source, arcname=f"{prefix}/LICENSE")
        archive.add(notice, arcname=f"{prefix}/NOTICE")
    return dist


def test_distribution_gate_accepts_matching_tag_and_writes_checksums(tmp_path: Path) -> None:
    root = _project(tmp_path)
    dist = _distributions(root)

    report = inspect_distribution(root, dist, tag=f"forgeos-v{PACKAGE_VERSION}")
    destination = dist / "SHA256SUMS"
    write_checksums(report, destination)

    assert report.package == "forgeos-harness"
    assert report.version == PACKAGE_VERSION
    assert len(report.artifacts) == 2
    assert destination.read_text(encoding="utf-8").splitlines() == [
        f"{artifact.sha256}  {artifact.name}" for artifact in report.artifacts
    ]


def test_distribution_gate_rejects_non_version_tag(tmp_path: Path) -> None:
    root = _project(tmp_path)
    dist = _distributions(root)

    with pytest.raises(ValueError, match="release tag must be"):
        inspect_distribution(root, dist, tag="forgeos-v0.2.0-rc.1")


def test_checksum_writer_is_deterministic(tmp_path: Path) -> None:
    payload = b"wheel"
    report = DistributionReport(
        package="forgeos-harness",
        version=PACKAGE_VERSION,
        tag=None,
        artifacts=(
            ReleaseArtifact("forge.whl", len(payload), hashlib.sha256(payload).hexdigest()),
        ),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    write_checksums(report, first)
    write_checksums(report, second)

    assert first.read_bytes() == second.read_bytes()
