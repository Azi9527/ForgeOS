"""Persistent execution attempts and step evidence for recoverable Forge runs."""

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .errors import ForgeConfigError, ForgeConflictError
from .storage import ForgeStore

SCHEMA_VERSION = 1


class AttemptState(str, Enum):
    """Authoritative lifecycle for one persisted execution attempt."""

    queued = "QUEUED"
    running = "RUNNING"
    interrupting = "INTERRUPTING"
    completed = "COMPLETED"
    failed = "FAILED"
    interrupted = "INTERRUPTED"

    @property
    def terminal(self) -> bool:
        return self in {self.completed, self.failed, self.interrupted}


class StepState(str, Enum):
    """Lifecycle of one committed execution step."""

    running = "RUNNING"
    completed = "COMPLETED"
    failed = "FAILED"
    interrupted = "INTERRUPTED"


@dataclass(frozen=True, slots=True)
class ExecutionStepResult:
    """Bounded evidence for one workflow step within an execution attempt."""

    name: str
    status: StepState
    started_at: str
    finished_at: str | None = None
    input_summary: dict[str, Any] | None = None
    output_summary: dict[str, Any] | None = None
    files_read: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _bounded_text(self.name, field="step name", maximum=120)
        _bounded_text(self.started_at, field="step started_at", maximum=80)
        if self.finished_at is not None:
            _bounded_text(self.finished_at, field="step finished_at", maximum=80)
        if self.error is not None:
            _bounded_text(self.error, field="step error", maximum=2_000, allow_empty=True)
        _bounded_items(self.files_read, field="files_read", count=2_000, item_size=1_000)
        _bounded_items(self.files_changed, field="files_changed", count=2_000, item_size=1_000)
        if len(self.commands) > 500:
            raise ValueError("commands exceeds 500 items")
        for command in self.commands:
            _bounded_items(command, field="command argv", count=200, item_size=2_000)
        _bounded_mapping(self.input_summary, field="input_summary")
        _bounded_mapping(self.output_summary, field="output_summary")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "status": self.status.value,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "files_read": list(self.files_read),
            "files_changed": list(self.files_changed),
            "commands": [list(argv) for argv in self.commands],
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionStepResult":
        _require_schema(value)
        return cls(
            name=_required_string(value, "name"),
            status=StepState(_required_string(value, "status")),
            started_at=_required_string(value, "started_at"),
            finished_at=_optional_string(value, "finished_at"),
            input_summary=_optional_mapping(value, "input_summary"),
            output_summary=_optional_mapping(value, "output_summary"),
            files_read=_string_tuple(value, "files_read"),
            files_changed=_string_tuple(value, "files_changed"),
            commands=_commands(value),
            error=_optional_string(value, "error", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """Recoverable persisted projection of one ForgeTask execution attempt."""

    id: str
    task_id: str
    kind: str
    status: AttemptState
    created_at: str
    revision: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    steps: tuple[ExecutionStepResult, ...] = ()
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, *, task_id: str, kind: str, created_at: str) -> "ExecutionAttempt":
        return cls(
            id=f"attempt-{uuid4()}",
            task_id=_safe_identifier(task_id, field="task_id"),
            kind=_bounded_text(kind, field="attempt kind", maximum=80),
            status=AttemptState.queued,
            created_at=_bounded_text(created_at, field="attempt created_at", maximum=80),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "kind": self.kind,
            "status": self.status.value,
            "created_at": self.created_at,
            "revision": self.revision,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "steps": [step.to_dict() for step in self.steps],
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExecutionAttempt":
        _require_schema(value)
        revision = value.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("attempt revision must be a non-negative integer")
        steps = value.get("steps")
        if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
            raise ValueError("attempt steps must be an array of objects")
        return cls(
            id=_safe_identifier(_required_string(value, "id"), field="attempt id"),
            task_id=_safe_identifier(_required_string(value, "task_id"), field="task_id"),
            kind=_required_string(value, "kind"),
            status=AttemptState(_required_string(value, "status")),
            created_at=_required_string(value, "created_at"),
            revision=revision,
            started_at=_optional_string(value, "started_at"),
            finished_at=_optional_string(value, "finished_at"),
            thread_id=_optional_string(value, "thread_id"),
            turn_id=_optional_string(value, "turn_id"),
            steps=tuple(ExecutionStepResult.from_dict(step) for step in steps),
            error=_optional_string(value, "error", allow_empty=True),
        )


class ExecutionAttemptRepository:
    """Atomically persist attempts and recover abandoned non-terminal records."""

    def __init__(self, store: ForgeStore) -> None:
        self.store = store

    def create(self, *, task_id: str, kind: str, created_at: str) -> ExecutionAttempt:
        attempt = ExecutionAttempt.create(task_id=task_id, kind=kind, created_at=created_at)
        lock_path = self._lock_path(attempt.id)
        with self.store.exclusive_lock(lock_path):
            path = self._path(attempt.task_id, attempt.id)
            if path.exists():
                raise ForgeConflictError(f"execution attempt already exists: {attempt.id}")
            self.store.write_json(path, attempt.to_dict())
        return attempt

    def load(self, task_id: str, attempt_id: str) -> ExecutionAttempt:
        return ExecutionAttempt.from_dict(self.store.read_json(self._path(task_id, attempt_id)))

    def list_for_task(self, task_id: str) -> tuple[ExecutionAttempt, ...]:
        safe_task_id = _safe_identifier(task_id, field="task_id")
        records = self.store.list_records(f"execution-attempts/{safe_task_id}")
        attempts = tuple(ExecutionAttempt.from_dict(record) for record in records)
        return tuple(sorted(attempts, key=lambda attempt: (attempt.created_at, attempt.id)))

    def save(self, attempt: ExecutionAttempt, *, expected_revision: int) -> ExecutionAttempt:
        lock_path = self._lock_path(attempt.id)
        with self.store.exclusive_lock(lock_path):
            current = self.load(attempt.task_id, attempt.id)
            if current.revision != expected_revision:
                raise ForgeConflictError(
                    f"attempt {attempt.id} revision changed: expected {expected_revision}, "
                    f"found {current.revision}"
                )
            if attempt.revision != expected_revision + 1:
                raise ForgeConflictError(
                    f"attempt {attempt.id} next revision must be {expected_revision + 1}"
                )
            self.store.write_json(self._path(attempt.task_id, attempt.id), attempt.to_dict())
        return attempt

    def start(self, attempt: ExecutionAttempt, *, started_at: str) -> ExecutionAttempt:
        if attempt.status is not AttemptState.queued:
            raise ForgeConflictError(f"attempt {attempt.id} is not QUEUED")
        updated = replace(
            attempt,
            status=AttemptState.running,
            started_at=started_at,
            revision=attempt.revision + 1,
        )
        return self.save(updated, expected_revision=attempt.revision)

    def attach_turn(
        self,
        attempt: ExecutionAttempt,
        *,
        thread_id: str,
        turn_id: str,
    ) -> ExecutionAttempt:
        if attempt.status is not AttemptState.running:
            raise ForgeConflictError(f"attempt {attempt.id} is not RUNNING")
        updated = replace(
            attempt,
            thread_id=_bounded_text(thread_id, field="thread_id", maximum=200),
            turn_id=_bounded_text(turn_id, field="turn_id", maximum=200),
            revision=attempt.revision + 1,
        )
        return self.save(updated, expected_revision=attempt.revision)

    def append_step(
        self,
        attempt: ExecutionAttempt,
        step: ExecutionStepResult,
    ) -> ExecutionAttempt:
        if attempt.status.terminal:
            raise ForgeConflictError(f"attempt {attempt.id} is terminal")
        updated = replace(
            attempt,
            steps=attempt.steps + (step,),
            revision=attempt.revision + 1,
        )
        return self.save(updated, expected_revision=attempt.revision)

    def request_interrupt(self, attempt: ExecutionAttempt) -> ExecutionAttempt:
        if attempt.status is AttemptState.interrupting:
            return attempt
        if attempt.status is not AttemptState.running:
            raise ForgeConflictError(f"attempt {attempt.id} is not RUNNING")
        updated = replace(
            attempt,
            status=AttemptState.interrupting,
            revision=attempt.revision + 1,
        )
        return self.save(updated, expected_revision=attempt.revision)

    def finish(
        self,
        attempt: ExecutionAttempt,
        *,
        status: AttemptState,
        finished_at: str,
        error: str | None = None,
    ) -> ExecutionAttempt:
        if status not in {
            AttemptState.completed,
            AttemptState.failed,
            AttemptState.interrupted,
        }:
            raise ValueError("finish status must be terminal")
        if attempt.status.terminal:
            if attempt.status is status:
                return attempt
            raise ForgeConflictError(f"attempt {attempt.id} is already terminal")
        updated = replace(
            attempt,
            status=status,
            finished_at=finished_at,
            error=_bounded_optional(error, maximum=2_000),
            revision=attempt.revision + 1,
        )
        return self.save(updated, expected_revision=attempt.revision)

    def recover_incomplete(self, *, recovered_at: str) -> tuple[ExecutionAttempt, ...]:
        root = self.store.forge_dir / "execution-attempts"
        if not root.exists():
            return ()
        recovered: list[ExecutionAttempt] = []
        for task_directory in sorted(root.iterdir()):
            if task_directory.is_symlink():
                raise ForgeConfigError(
                    f"attempt directory must not be a symbolic link: {task_directory}"
                )
            if not task_directory.is_dir():
                continue
            for path in sorted(task_directory.glob("*.json")):
                attempt = ExecutionAttempt.from_dict(self.store.read_json(path))
                if attempt.status.terminal:
                    continue
                recovered.append(
                    self.finish(
                        attempt,
                        status=AttemptState.interrupted,
                        finished_at=recovered_at,
                        error="ForgeOS process ended before the attempt reached a terminal state",
                    )
                )
        return tuple(recovered)

    def _path(self, task_id: str, attempt_id: str) -> Path:
        safe_task = _safe_identifier(task_id, field="task_id")
        safe_attempt = _safe_identifier(attempt_id, field="attempt id")
        return self.store.forge_dir / "execution-attempts" / safe_task / f"{safe_attempt}.json"

    def _lock_path(self, attempt_id: str) -> Path:
        safe_attempt = _safe_identifier(attempt_id, field="attempt id")
        return self.store.forge_dir / "execution-attempts" / f".{safe_attempt}.lock"


def _safe_identifier(value: str, *, field: str) -> str:
    normalized = _bounded_text(value, field=field, maximum=200)
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
    if any(character not in allowed for character in normalized):
        raise ValueError(f"{field} contains unsafe characters")
    return normalized


def _bounded_text(
    value: str,
    *,
    field: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field} must not be empty")
    if len(value) > maximum:
        raise ValueError(f"{field} exceeds {maximum} characters")
    return value


def _bounded_optional(value: str | None, *, maximum: int) -> str | None:
    if value is None:
        return None
    return value if len(value) <= maximum else value[:maximum] + "\n[TRUNCATED BY FORGEOS]"


def _bounded_items(values: tuple[str, ...], *, field: str, count: int, item_size: int) -> None:
    if len(values) > count:
        raise ValueError(f"{field} exceeds {count} items")
    for value in values:
        _bounded_text(value, field=field, maximum=item_size, allow_empty=True)


def _bounded_mapping(value: dict[str, Any] | None, *, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    import json

    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 16_384:
        raise ValueError(f"{field} exceeds 16384 bytes")


def _require_schema(value: dict[str, Any]) -> None:
    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported execution schema_version: {value.get('schema_version')!r}")


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return item


def _optional_string(
    value: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or (not allow_empty and not item.strip()):
        raise ValueError(f"{key} must be null or a string")
    return item


def _optional_mapping(value: dict[str, Any], key: str) -> dict[str, Any] | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, dict):
        raise ValueError(f"{key} must be null or an object")
    return dict(item)


def _string_tuple(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key, [])
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(items)


def _commands(value: dict[str, Any]) -> tuple[tuple[str, ...], ...]:
    commands = value.get("commands", [])
    if not isinstance(commands, list) or not all(
        isinstance(command, list) and all(isinstance(item, str) for item in command)
        for command in commands
    ):
        raise ValueError("commands must be an array of argv arrays")
    return tuple(tuple(command) for command in commands)
