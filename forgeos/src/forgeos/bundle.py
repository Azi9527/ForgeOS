"""Verified, deterministic export and atomic import of `.forge` evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .errors import ForgeBundleError, ForgeConflictError, ForgeIntegrityError
from .integrity import IntegrityService
from .migration import CURRENT_PROTOCOL_VERSION
from .storage import ForgeStore

BUNDLE_SCHEMA_VERSION = 1
MAX_BUNDLE_FILES = 10_000
MAX_BUNDLE_BYTES = 268_435_456
MAX_BUNDLE_FILE_BYTES = 16_777_216
MAX_MANIFEST_BYTES = 8_388_608
_FIXED_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


@dataclass(frozen=True, slots=True)
class BundleEntry:
    path: str
    size: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BundleEntry":
        path = value.get("path")
        size = value.get("size")
        digest = value.get("sha256")
        if not isinstance(path, str) or not _safe_relative(path):
            raise ForgeBundleError("bundle entry has an unsafe path")
        if not isinstance(size, int) or not 0 <= size <= MAX_BUNDLE_FILE_BYTES:
            raise ForgeBundleError(f"bundle entry has invalid size: {path}")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ForgeBundleError(f"bundle entry has invalid sha256: {path}")
        try:
            bytes.fromhex(digest)
        except ValueError as exc:
            raise ForgeBundleError(f"bundle entry has invalid sha256: {path}") from exc
        return cls(path, size, digest)


@dataclass(frozen=True, slots=True)
class BundleManifest:
    source_project_id: str
    source_project_name: str
    protocol_version: int
    entries: tuple[BundleEntry, ...]
    schema_version: int = BUNDLE_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_project_id": self.source_project_id,
            "source_project_name": self.source_project_name,
            "protocol_version": self.protocol_version,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BundleManifest":
        if value.get("schema_version") != BUNDLE_SCHEMA_VERSION:
            raise ForgeBundleError("unsupported bundle schema_version")
        protocol = value.get("protocol_version")
        entries = value.get("entries")
        if protocol != CURRENT_PROTOCOL_VERSION:
            raise ForgeBundleError(f"unsupported bundle protocol_version: {protocol!r}")
        if not isinstance(entries, list) or len(entries) > MAX_BUNDLE_FILES:
            raise ForgeBundleError("bundle entries must be a bounded array")
        parsed = tuple(BundleEntry.from_dict(entry) for entry in entries if isinstance(entry, dict))
        if len(parsed) != len(entries) or len({entry.path for entry in parsed}) != len(parsed):
            raise ForgeBundleError("bundle entries are invalid or duplicated")
        return cls(
            source_project_id=_required_text(value, "source_project_id"),
            source_project_name=_required_text(value, "source_project_name"),
            protocol_version=protocol,
            entries=parsed,
        )


@dataclass(frozen=True, slots=True)
class BundleVerification:
    path: str
    bundle_sha256: str
    file_count: int
    total_bytes: int
    manifest: BundleManifest
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "bundle_sha256": self.bundle_sha256,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "manifest": self.manifest.to_dict(),
            "passed": True,
        }


class ForgeBundleService:
    """Export verified state and import only into an empty Forge workspace."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock

    def export(self, destination: Path) -> BundleVerification:
        config = self.store.load_config()
        integrity = IntegrityService(self.store, clock=self.clock).scan(persist=False)
        if not integrity.passed:
            raise ForgeIntegrityError("cannot export Forge evidence with integrity errors")
        target = destination.resolve(strict=False)
        if target.exists():
            raise ForgeConflictError(f"export destination already exists: {target}")
        if target.is_relative_to(self.store.forge_dir):
            raise ForgeBundleError("export destination must be outside .forge")
        files = self._source_files()
        entries = tuple(_entry(path, self.store.forge_dir) for path in files)
        manifest = BundleManifest(
            source_project_id=config.project.id,
            source_project_name=config.project.name,
            protocol_version=CURRENT_PROTOCOL_VERSION,
            entries=entries,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
        try:
            with zipfile.ZipFile(temporary, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                _write_zip(archive, "manifest.json", _json_bytes(manifest.to_dict()))
                for path, entry in zip(files, entries, strict=True):
                    _write_zip(archive, f"files/{entry.path}", path.read_bytes())
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        verification = self.verify(target)
        self.store.write_record(
            f"exports/export-{uuid4()}.json",
            {
                "schema_version": 1,
                "exported_at": self.clock(),
                "path": str(target),
                "bundle_sha256": verification.bundle_sha256,
                "file_count": verification.file_count,
            },
        )
        AuditLog(self.store, clock=self.clock).append(
            "bundle.exported",
            actor=AuditActor.human,
            payload={"bundle_sha256": verification.bundle_sha256, "file_count": len(entries)},
        )
        return verification

    def verify(self, source: Path) -> BundleVerification:
        path = source.resolve(strict=True)
        if not path.is_file():
            raise ForgeBundleError(f"bundle is not a file: {path}")
        try:
            with zipfile.ZipFile(path, "r") as archive:
                names = archive.namelist()
                if len(names) > MAX_BUNDLE_FILES + 1:
                    raise ForgeBundleError("bundle exceeds the file count limit")
                if len(names) != len(set(names)) or "manifest.json" not in names:
                    raise ForgeBundleError("bundle contains duplicate entries or no manifest")
                manifest_info = archive.getinfo("manifest.json")
                if manifest_info.file_size > MAX_MANIFEST_BYTES or _is_symlink(manifest_info):
                    raise ForgeBundleError("bundle manifest is oversized or unsafe")
                manifest_value = json.loads(archive.read("manifest.json"))
                if not isinstance(manifest_value, dict):
                    raise ForgeBundleError("bundle manifest must be an object")
                manifest = BundleManifest.from_dict(manifest_value)
                expected = {"manifest.json", *(f"files/{entry.path}" for entry in manifest.entries)}
                if set(names) != expected:
                    raise ForgeBundleError("bundle file set does not match its manifest")
                total = 0
                for entry in manifest.entries:
                    info = archive.getinfo(f"files/{entry.path}")
                    if info.is_dir() or _is_symlink(info) or info.file_size != entry.size:
                        raise ForgeBundleError(f"bundle size mismatch: {entry.path}")
                    total += info.file_size
                    if total > MAX_BUNDLE_BYTES:
                        raise ForgeBundleError("bundle exceeds the uncompressed size limit")
                    payload = archive.read(info)
                    if hashlib.sha256(payload).hexdigest() != entry.sha256:
                        raise ForgeBundleError(f"bundle hash mismatch: {entry.path}")
        except (OSError, ValueError, zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
            if isinstance(exc, ForgeBundleError):
                raise
            raise ForgeBundleError(f"invalid Forge bundle: {exc}") from exc
        return BundleVerification(
            path=str(path),
            bundle_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            file_count=len(manifest.entries),
            total_bytes=sum(entry.size for entry in manifest.entries),
            manifest=manifest,
        )

    def import_bundle(self, source: Path) -> BundleVerification:
        if self.store.forge_dir.exists():
            raise ForgeConflictError("bundle import requires a workspace without .forge")
        verification = self.verify(source)
        staging = self.store.project_root / f".forge-import-{uuid4().hex}"
        try:
            staging.mkdir()
            with zipfile.ZipFile(source.resolve(strict=True), "r") as archive:
                for entry in verification.manifest.entries:
                    target = staging / Path(entry.path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.read(f"files/{entry.path}"))
            config_path = staging / "forge.yaml"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["project"]["root"] = str(self.store.project_root)
            config_path.write_bytes(_json_bytes(config))
            os.replace(staging, self.store.forge_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        self.store.ensure_layout()
        self.store.load_config()
        self.store.write_record(
            f"imports/import-{uuid4()}.json",
            {
                "schema_version": 1,
                "imported_at": self.clock(),
                "bundle_sha256": verification.bundle_sha256,
                "source_project_id": verification.manifest.source_project_id,
            },
        )
        AuditLog(self.store, clock=self.clock).append(
            "bundle.imported",
            actor=AuditActor.human,
            payload={"bundle_sha256": verification.bundle_sha256},
        )
        return verification

    def _source_files(self) -> tuple[Path, ...]:
        files: list[Path] = []
        for path in self.store.forge_dir.rglob("*"):
            if path.is_symlink():
                raise ForgeBundleError(f"bundle source contains a symbolic link: {path}")
            if not path.is_file():
                continue
            relative = path.relative_to(self.store.forge_dir).as_posix()
            if relative.startswith("exports/") or path.name.endswith((".lock", ".tmp")):
                continue
            if path.stat().st_size > MAX_BUNDLE_FILE_BYTES:
                raise ForgeBundleError(f"bundle source file is too large: {relative}")
            files.append(path)
        if len(files) > MAX_BUNDLE_FILES:
            raise ForgeBundleError("bundle source exceeds file count limit")
        return tuple(
            sorted(files, key=lambda path: path.relative_to(self.store.forge_dir).as_posix())
        )


def _entry(path: Path, root: Path) -> BundleEntry:
    payload = path.read_bytes()
    return BundleEntry(
        path=path.relative_to(root).as_posix(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ForgeBundleError(f"bundle manifest {key} must be a non-empty string")
    return item.strip()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _write_zip(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, _FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100600 << 16
    archive.writestr(info, payload)


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000
