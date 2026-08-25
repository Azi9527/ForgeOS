"""Read-only, bounded Git evidence capture for Forge execution baselines."""

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from uuid import uuid4

from .errors import ForgeRuntimeUnavailableError
from .storage import ForgeStore

SCHEMA_VERSION = 1
DEFAULT_OUTPUT_LIMIT = 1_048_576


@dataclass(frozen=True, slots=True)
class GitSnapshot:
    """One immutable baseline or current Git projection with bounded details."""

    id: str
    task_id: str
    kind: str
    captured_at: str
    available: bool
    repository_root: str | None
    head: str | None
    branch: str | None
    detached: bool
    dirty: bool
    changed_files: tuple[str, ...]
    status_sha256: str | None
    diff_sha256: str | None
    status_truncated: bool = False
    warning: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "kind": self.kind,
            "captured_at": self.captured_at,
            "available": self.available,
            "repository_root": self.repository_root,
            "head": self.head,
            "branch": self.branch,
            "detached": self.detached,
            "dirty": self.dirty,
            "changed_files": list(self.changed_files),
            "status_sha256": self.status_sha256,
            "diff_sha256": self.diff_sha256,
            "status_truncated": self.status_truncated,
            "warning": self.warning,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GitSnapshot":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported GitSnapshot schema: {value.get('schema_version')!r}")
        changed_files = value.get("changed_files")
        if not isinstance(changed_files, list) or not all(
            isinstance(item, str) for item in changed_files
        ):
            raise ValueError("changed_files must be an array of strings")
        return cls(
            id=_required_string(value, "id"),
            task_id=_required_string(value, "task_id"),
            kind=_required_string(value, "kind"),
            captured_at=_required_string(value, "captured_at"),
            available=_required_bool(value, "available"),
            repository_root=_optional_string(value, "repository_root"),
            head=_optional_string(value, "head"),
            branch=_optional_string(value, "branch"),
            detached=_required_bool(value, "detached"),
            dirty=_required_bool(value, "dirty"),
            changed_files=tuple(changed_files),
            status_sha256=_optional_string(value, "status_sha256"),
            diff_sha256=_optional_string(value, "diff_sha256"),
            status_truncated=_required_bool(value, "status_truncated"),
            warning=_optional_string(value, "warning"),
        )


@dataclass(frozen=True, slots=True)
class _CommandResult:
    exit_code: int
    output: bytes
    output_sha256: str
    truncated: bool
    stderr: str


class GitEvidenceService:
    """Capture Git state without mutating the repository or invoking a shell."""

    def __init__(
        self,
        workspace: Path,
        *,
        clock: Callable[[], str],
        timeout_seconds: float = 10.0,
        output_limit: int = DEFAULT_OUTPUT_LIMIT,
    ) -> None:
        self.workspace = workspace.resolve()
        self.clock = clock
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        self.git = shutil.which("git")

    def capture(self, task_id: str, *, kind: str) -> GitSnapshot:
        snapshot_id = f"git-{uuid4()}"
        if self.git is None:
            return self._unavailable(snapshot_id, task_id, kind, "git executable not found")
        root = self._run(("rev-parse", "--show-toplevel"))
        if root.exit_code != 0:
            return self._unavailable(
                snapshot_id, task_id, kind, "workspace is not a Git repository"
            )
        repository_root = _decode(root.output).strip()
        head_result = self._run(("rev-parse", "HEAD"))
        if head_result.exit_code != 0:
            return self._unavailable(snapshot_id, task_id, kind, "Git repository has no HEAD")
        head = _decode(head_result.output).strip()
        branch_result = self._run(("symbolic-ref", "--quiet", "--short", "HEAD"))
        branch = _decode(branch_result.output).strip() if branch_result.exit_code == 0 else None
        status = self._run(
            (
                "-c",
                "core.quotepath=false",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--",
                ".",
            )
        )
        if status.exit_code != 0:
            return self._unavailable(
                snapshot_id, task_id, kind, status.stderr or "git status failed"
            )
        unstaged = self._run(("diff", "--no-ext-diff", "--binary", "--", "."))
        staged = self._run(("diff", "--cached", "--no-ext-diff", "--binary", "--", "."))
        diff_hash = hashlib.sha256(
            f"unstaged:{unstaged.output_sha256}\nstaged:{staged.output_sha256}".encode()
        ).hexdigest()
        changed_files = () if status.truncated else _status_paths(status.output)
        return GitSnapshot(
            id=snapshot_id,
            task_id=task_id,
            kind=kind,
            captured_at=self.clock(),
            available=True,
            repository_root=repository_root,
            head=head,
            branch=branch,
            detached=branch is None,
            dirty=bool(status.output),
            changed_files=changed_files,
            status_sha256=status.output_sha256,
            diff_sha256=diff_hash,
            status_truncated=status.truncated,
            warning="status path list exceeded the capture limit" if status.truncated else None,
        )

    def capture_and_store(self, store: ForgeStore, task_id: str, *, kind: str) -> GitSnapshot:
        snapshot = self.capture(task_id, kind=kind)
        store.write_record(
            f"evidence/git/{task_id}/{snapshot.id}.json",
            snapshot.to_dict(),
        )
        return snapshot

    def _run(self, args: tuple[str, ...]) -> _CommandResult:
        if self.git is None:
            raise ForgeRuntimeUnavailableError("git executable not found")
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    (self.git, *args),
                    cwd=self.workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=self.timeout_seconds,
                    shell=False,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return _CommandResult(
                    exit_code=124,
                    output=b"",
                    output_sha256=hashlib.sha256(b"").hexdigest(),
                    truncated=False,
                    stderr=f"git command timed out after {self.timeout_seconds:g}s",
                )
            stdout.seek(0)
            digest = hashlib.sha256()
            captured = bytearray()
            truncated = False
            while chunk := stdout.read(65_536):
                digest.update(chunk)
                remaining = self.output_limit - len(captured)
                if remaining > 0:
                    captured.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
            stderr.seek(0)
            error = stderr.read(8_192)
        return _CommandResult(
            exit_code=completed.returncode,
            output=bytes(captured),
            output_sha256=digest.hexdigest(),
            truncated=truncated,
            stderr=_decode(error).strip(),
        )

    def _unavailable(self, snapshot_id: str, task_id: str, kind: str, warning: str) -> GitSnapshot:
        return GitSnapshot(
            id=snapshot_id,
            task_id=task_id,
            kind=kind,
            captured_at=self.clock(),
            available=False,
            repository_root=None,
            head=None,
            branch=None,
            detached=False,
            dirty=False,
            changed_files=(),
            status_sha256=None,
            diff_sha256=None,
            warning=warning[:2_000],
        )


def _status_paths(value: bytes) -> tuple[str, ...]:
    entries = value.split(b"\0")
    paths: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        if len(entry) < 4:
            raise ValueError("invalid porcelain status entry")
        code = entry[:2]
        paths.add(_normalize_git_path(os.fsdecode(entry[3:])))
        if b"R" in code or b"C" in code:
            if index >= len(entries) or not entries[index]:
                raise ValueError("rename status entry is missing its source path")
            paths.add(_normalize_git_path(os.fsdecode(entries[index])))
            index += 1
    return tuple(sorted(paths))


def _normalize_git_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe Git path: {value}")
    return str(path)


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"{key} must be null or a string")
    return item


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be a boolean")
    return item
