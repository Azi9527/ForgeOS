"""File-backed ForgeOS persistence with canonical path and revision checks."""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .config import ForgeConfig
from .errors import ForgeConfigError, ForgeConflictError, ForgeNotFoundError
from .models import ForgeTask, TaskStatus

_LAYOUT = (
    "context",
    "rules",
    "tasks/active",
    "tasks/completed",
    "tasks/failed",
    "workflows",
    "validation/results",
    "validation/baselines",
    "validation/regression",
    "memory/decisions",
    "memory/failures",
    "memory/patterns",
    "memory/tasks",
    "memory/selections",
    "policies",
    "policies/retired",
    "policy/evaluations",
    "budget/evaluations",
    "recovery/cancellations",
    "recovery/runs",
    "integrity/scans",
    "migrations",
    "release/checks",
    "exports",
    "imports",
    "logs",
    "executions",
    "execution-attempts",
    "evidence/git",
    "context/packages",
    "reports",
)


class ForgeStore:
    """Persist authoritative Forge objects under one project `.forge/` root."""

    def __init__(self, project_root: Path) -> None:
        root = project_root.resolve()
        if not root.is_dir():
            raise ValueError(f"project_root must be an existing directory: {root}")
        self.project_root = root
        self.forge_dir = root / ".forge"

    @property
    def config_path(self) -> Path:
        return self.forge_dir / "forge.yaml"

    def is_initialized(self) -> bool:
        return self.config_path.is_file()

    def initialize(self, config: ForgeConfig) -> None:
        if Path(config.project.root).resolve() != self.project_root:
            raise ForgeConfigError("config project root does not match the store root")
        if self.forge_dir.exists() and self.forge_dir.is_symlink():
            raise ForgeConfigError(".forge must not be a symbolic link")

        self.forge_dir.mkdir(exist_ok=True)
        self.ensure_layout()

        if self.config_path.exists():
            existing = self.load_config()
            if existing != config:
                raise ForgeConflictError(
                    "existing forge.yaml conflicts with requested configuration"
                )
            return
        self.write_json(self.config_path, config.to_dict())

    def ensure_layout(self) -> None:
        """Add missing protocol directories without modifying persisted objects."""

        if self.forge_dir.exists() and self.forge_dir.is_symlink():
            raise ForgeConfigError(".forge must not be a symbolic link")
        self.forge_dir.mkdir(exist_ok=True)
        for relative in _LAYOUT:
            self._safe_path(relative).mkdir(parents=True, exist_ok=True)

    def load_config(self) -> ForgeConfig:
        self._require_initialized()
        try:
            config = ForgeConfig.from_dict(self.read_json(self.config_path))
            if Path(config.project.root).resolve() != self.project_root:
                raise ForgeConfigError(
                    "forge.yaml project root does not match the current workspace"
                )
            return config
        except ForgeNotFoundError:
            raise
        except (ValueError, json.JSONDecodeError) as exc:
            raise ForgeConfigError(f"invalid forge.yaml: {exc}") from exc

    def allocate_task_id(self, prefix: str) -> str:
        self._require_initialized()
        lock_path = self._safe_path("tasks/.sequence.lock")
        with self.exclusive_lock(lock_path):
            sequence_path = self._safe_path("tasks/sequence.json")
            if sequence_path.exists():
                value = self.read_json(sequence_path)
                sequence = value.get("last")
                if not isinstance(sequence, int) or sequence < 0:
                    raise ForgeConfigError("tasks/sequence.json contains an invalid sequence")
            else:
                sequence = 0
            sequence += 1
            self.write_json(sequence_path, {"schema_version": 1, "last": sequence})
        return f"{prefix.upper()}-{sequence:04d}"

    def load_task(self, task_id: str) -> ForgeTask:
        path = self._find_task_path(task_id)
        try:
            return ForgeTask.from_dict(self.read_json(path))
        except (ValueError, json.JSONDecodeError) as exc:
            raise ForgeConfigError(f"invalid task {task_id}: {exc}") from exc

    def list_tasks(self) -> tuple[ForgeTask, ...]:
        self._require_initialized()
        task_ids: list[str] = []
        for bucket in ("active", "completed", "failed"):
            directory = self._safe_path(f"tasks/{bucket}")
            task_ids.extend(path.stem for path in directory.glob("*.json") if path.is_file())
        if len(task_ids) != len(set(task_ids)):
            raise ForgeConflictError("a task has multiple persisted projections")
        return tuple(self.load_task(task_id) for task_id in sorted(task_ids))

    def save_new_task(self, task: ForgeTask) -> None:
        self._require_initialized()
        lock_path = self._safe_path(f"tasks/.{_task_filename(task.id)}.lock")
        with self.exclusive_lock(lock_path):
            if self._existing_task_path(task.id) is not None:
                raise ForgeConflictError(f"task already exists: {task.id}")
            self.write_json(self._task_path(task), task.to_dict())

    def save_task(self, task: ForgeTask, *, expected_revision: int) -> None:
        self._require_initialized()
        lock_path = self._safe_path(f"tasks/.{_task_filename(task.id)}.lock")
        with self.exclusive_lock(lock_path):
            current_path = self._find_task_path(task.id)
            current = self.load_task(task.id)
            if current.revision != expected_revision:
                raise ForgeConflictError(
                    f"task {task.id} revision changed: expected {expected_revision}, "
                    f"found {current.revision}"
                )
            if task.revision != expected_revision + 1:
                raise ForgeConflictError(
                    f"task {task.id} next revision must be {expected_revision + 1}, "
                    f"found {task.revision}"
                )

            target_path = self._task_path(task)
            self.write_json(target_path, task.to_dict())
            if current_path != target_path:
                current_path.unlink()

    def write_record(self, relative: str, value: dict[str, Any]) -> Path:
        self._require_initialized()
        path = self._safe_path(relative)
        self.write_json(path, value)
        return path

    def list_records(self, relative: str) -> tuple[dict[str, Any], ...]:
        """Read JSON records from one Forge directory in stable filename order."""

        self._require_initialized()
        directory = self._safe_path(relative)
        if not directory.exists():
            return ()
        if not directory.is_dir():
            raise ForgeConfigError(f"Forge record path must be a directory: {directory}")
        return tuple(self.read_json(path) for path in sorted(directory.glob("*.json")))

    def read_json(self, path: Path) -> dict[str, Any]:
        safe_path = self._safe_existing_path(path)
        if not safe_path.is_file():
            raise ForgeNotFoundError(f"Forge file not found: {safe_path}")
        value = json.loads(safe_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ForgeConfigError(f"Forge file must contain an object: {safe_path}")
        return value

    def write_json(self, path: Path, value: dict[str, Any]) -> None:
        safe_path = self._safe_new_path(path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary = safe_path.with_name(f".{safe_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, safe_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    @contextmanager
    def exclusive_lock(self, lock_path: Path, *, timeout_seconds: float = 5.0) -> Iterator[None]:
        safe_lock = self._safe_new_path(lock_path)
        safe_lock.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(safe_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError) as exc:
                if isinstance(exc, PermissionError) and os.name != "nt":
                    raise
                try:
                    lock_age = time.time() - safe_lock.stat().st_mtime
                except FileNotFoundError:
                    if isinstance(exc, PermissionError):
                        raise exc from None
                    continue
                if lock_age > 60:
                    try:
                        safe_lock.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise ForgeConflictError(
                        f"timed out waiting for Forge lock: {safe_lock}"
                    ) from None
                time.sleep(0.01)
        try:
            os.write(descriptor, f"pid={os.getpid()}\n".encode())
            os.close(descriptor)
            descriptor = None
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if safe_lock.exists():
                safe_lock.unlink()

    def _require_initialized(self) -> None:
        if not self.is_initialized():
            raise ForgeNotFoundError(f"ForgeOS is not initialized in {self.project_root}")

    def _find_task_path(self, task_id: str) -> Path:
        path = self._existing_task_path(task_id)
        if path is None:
            raise ForgeNotFoundError(f"task not found: {task_id}")
        return path

    def _existing_task_path(self, task_id: str) -> Path | None:
        safe_name = _task_filename(task_id)
        matches = [
            self._safe_path(f"tasks/{bucket}/{safe_name}")
            for bucket in ("active", "completed", "failed")
            if self._safe_path(f"tasks/{bucket}/{safe_name}").is_file()
        ]
        if len(matches) > 1:
            raise ForgeConflictError(f"task has multiple persisted projections: {task_id}")
        return matches[0] if matches else None

    def _task_path(self, task: ForgeTask) -> Path:
        if task.status is TaskStatus.done:
            bucket = "completed"
        elif task.status in {TaskStatus.failed, TaskStatus.cancelled}:
            bucket = "failed"
        else:
            bucket = "active"
        return self._safe_path(f"tasks/{bucket}/{_task_filename(task.id)}")

    def _safe_path(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise ForgeConfigError(f"unsafe Forge relative path: {relative}")
        return self._safe_new_path(self.forge_dir / path)

    def _safe_existing_path(self, path: Path) -> Path:
        safe_path = self._safe_new_path(path)
        if safe_path.is_symlink():
            raise ForgeConfigError(f"Forge path must not be a symbolic link: {safe_path}")
        return safe_path

    def _safe_new_path(self, path: Path) -> Path:
        absolute = path if path.is_absolute() else self.project_root / path
        candidate = type(absolute)(os.path.abspath(absolute))
        try:
            relative = candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise ForgeConfigError(f"Forge path escapes project root: {path}") from exc

        current = self.project_root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ForgeConfigError(f"Forge path contains a symbolic link: {current}")
        return candidate


def _task_filename(task_id: str) -> str:
    if not task_id or any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in task_id
    ):
        raise ForgeConfigError(f"invalid task id for storage: {task_id!r}")
    return f"{task_id}.json"
