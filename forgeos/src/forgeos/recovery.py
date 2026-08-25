"""Durable cancellation requests and startup recovery reconciliation."""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .errors import ForgeConflictError, ForgeNotFoundError
from .execution_records import ExecutionAttemptRepository
from .governance import validate_human_authority
from .models import ForgeTask, TaskStatus
from .service import ForgeService
from .storage import ForgeStore


class CancellationStatus(str, Enum):
    requested = "REQUESTED"
    applied = "APPLIED"


@dataclass(frozen=True, slots=True)
class CancellationRequest:
    id: str
    task_id: str
    status: CancellationStatus
    requested_at: str
    requested_by: str
    reason: str
    revision: int = 0
    applied_at: str | None = None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "status": self.status.value,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "reason": self.reason,
            "revision": self.revision,
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CancellationRequest":
        if value.get("schema_version") != 1:
            raise ValueError("unsupported CancellationRequest schema_version")
        revision = value.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("cancellation revision must be non-negative")
        applied_at = value.get("applied_at")
        if applied_at is not None and not isinstance(applied_at, str):
            raise ValueError("applied_at must be null or a string")
        return cls(
            id=_text(value, "id"),
            task_id=_text(value, "task_id"),
            status=CancellationStatus(_text(value, "status")),
            requested_at=_text(value, "requested_at"),
            requested_by=_text(value, "requested_by"),
            reason=_text(value, "reason"),
            revision=revision,
            applied_at=applied_at,
        )


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    id: str
    recovered_at: str
    interrupted_attempt_ids: tuple[str, ...]
    blocked_task_ids: tuple[str, ...]
    cancelled_task_ids: tuple[str, ...]
    warnings: tuple[str, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "recovered_at": self.recovered_at,
            "interrupted_attempt_ids": list(self.interrupted_attempt_ids),
            "blocked_task_ids": list(self.blocked_task_ids),
            "cancelled_task_ids": list(self.cancelled_task_ids),
            "warnings": list(self.warnings),
        }


class CancellationService:
    """Persist human cancellation intent until a safe lifecycle boundary applies it."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def request(self, task: ForgeTask, *, requested_by: str, reason: str) -> CancellationRequest:
        validate_human_authority(requested_by, "task cancellation")
        if task.status in {TaskStatus.done, TaskStatus.failed, TaskStatus.cancelled}:
            raise ForgeConflictError(f"terminal task {task.status.value} cannot be cancelled")
        reason = reason.strip()
        if not reason or len(reason) > 2_000:
            raise ValueError("cancellation reason must contain 1..2000 characters")
        path = self.store.forge_dir / "recovery" / "cancellations" / f"{task.id}.json"
        lock = self.store.forge_dir / "recovery" / "cancellations" / f".{task.id}.lock"
        with self.store.exclusive_lock(lock):
            existing = self.for_task(task.id)
            if existing is not None:
                if existing.status is CancellationStatus.requested:
                    return existing
                raise ForgeConflictError(f"task {task.id} cancellation was already applied")
            request = CancellationRequest(
                id=f"cancellation-{uuid4()}",
                task_id=task.id,
                status=CancellationStatus.requested,
                requested_at=self.clock(),
                requested_by=requested_by.strip(),
                reason=reason,
            )
            self.store.write_json(path, request.to_dict())
        self.audit.append(
            "task.cancellation_requested",
            actor=AuditActor.human,
            task_id=task.id,
            payload={"cancellation_id": request.id, "reason": reason},
        )
        return request

    def for_task(self, task_id: str) -> CancellationRequest | None:
        path = self.store.forge_dir / "recovery" / "cancellations" / f"{task_id}.json"
        if not path.exists():
            return None
        return CancellationRequest.from_dict(self.store.read_json(path))

    def pending(self, task_id: str) -> CancellationRequest | None:
        request = self.for_task(task_id)
        return (
            request
            if request is not None and request.status is CancellationStatus.requested
            else None
        )

    def apply(self, forge: ForgeService, task: ForgeTask) -> ForgeTask | None:
        current = task
        path = self.store.forge_dir / "recovery" / "cancellations" / f"{current.id}.json"
        lock = self.store.forge_dir / "recovery" / "cancellations" / f".{current.id}.lock"
        with self.store.exclusive_lock(lock):
            request = self.pending(current.id)
            if request is None:
                return None
            if current.status is TaskStatus.cancelled:
                updated_task = current
            elif current.status in {TaskStatus.done, TaskStatus.failed}:
                raise ForgeConflictError(
                    f"cannot apply cancellation to terminal task {current.status.value}"
                )
            else:
                updated_task = forge.transition_task(
                    current.id,
                    TaskStatus.cancelled,
                    expected_revision=current.revision,
                    reason=request.reason,
                    actor=AuditActor.human,
                )
            updated = replace(
                request,
                status=CancellationStatus.applied,
                applied_at=self.clock(),
                revision=request.revision + 1,
            )
            self.store.write_json(path, updated.to_dict())
        self.audit.append(
            "task.cancellation_applied",
            actor=AuditActor.system,
            task_id=current.id,
            payload={"cancellation_id": request.id, "revision": updated.revision},
        )
        return updated_task


class RecoveryService:
    """Reconcile abandoned attempts with authoritative Task state after restart."""

    def __init__(self, forge: ForgeService) -> None:
        self.forge = forge
        self.attempts = ExecutionAttemptRepository(forge.store)
        self.cancellations = CancellationService(forge.store, clock=forge.clock)

    def recover(self) -> RecoveryReport:
        recovered_at = self.forge.clock()
        attempts = self.attempts.recover_incomplete(recovered_at=recovered_at)
        blocked: list[str] = []
        cancelled: list[str] = []
        warnings: list[str] = []
        for task_id in sorted({attempt.task_id for attempt in attempts}):
            try:
                task = self.forge.task(task_id)
                if self.cancellations.pending(task_id) is not None:
                    updated = self.cancellations.apply(self.forge, task)
                    if updated is not None:
                        cancelled.append(task_id)
                elif task.status not in {
                    TaskStatus.blocked,
                    TaskStatus.done,
                    TaskStatus.failed,
                    TaskStatus.cancelled,
                }:
                    self.forge.transition_task(
                        task.id,
                        TaskStatus.blocked,
                        expected_revision=task.revision,
                        reason="ForgeOS recovered an abandoned execution attempt",
                        actor=AuditActor.system,
                    )
                    blocked.append(task_id)
            except (ForgeConflictError, ForgeNotFoundError, ValueError) as exc:
                warnings.append(f"{task_id}: {exc}")
        report = RecoveryReport(
            id=f"recovery-{uuid4()}",
            recovered_at=recovered_at,
            interrupted_attempt_ids=tuple(attempt.id for attempt in attempts),
            blocked_task_ids=tuple(blocked),
            cancelled_task_ids=tuple(cancelled),
            warnings=tuple(warnings),
        )
        self.forge.store.write_record(f"recovery/runs/{report.id}.json", report.to_dict())
        self.forge.audit.append(
            "recovery.completed",
            actor=AuditActor.system,
            payload={
                "recovery_id": report.id,
                "interrupted_attempts": len(attempts),
                "blocked_tasks": blocked,
                "cancelled_tasks": cancelled,
                "warning_count": len(warnings),
            },
        )
        return report


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return item
