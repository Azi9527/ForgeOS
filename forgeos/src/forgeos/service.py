"""Application service owning ForgeProject and ForgeTask mutations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .audit import AuditActor, AuditLog
from .config import ForgeConfig, ValidationCheckConfig
from .errors import ForgeConflictError
from .governance import (
    AcceptanceEvidence,
    ReviewEvidence,
    validate_acceptance_evidence,
    validate_human_authority,
    validate_review_evidence,
)
from .migration import CURRENT_PROTOCOL_VERSION
from .models import (
    ForgeProject,
    ForgeTask,
    TaskPriority,
    TaskRisk,
    TaskStatus,
    TaskType,
    ValidationEvidence,
)
from .storage import ForgeStore
from .task_state import TaskStateMachine

Clock = Callable[[], str]


class ForgeService:
    """Coordinate domain validation, persistence, and audit atomically by revision."""

    def __init__(
        self,
        project_root: Path,
        *,
        clock: Clock | None = None,
        ensure_layout: bool = True,
    ) -> None:
        self.clock = clock or utc_now
        self.store = ForgeStore(project_root)
        if ensure_layout and self.store.is_initialized():
            self.store.ensure_layout()
        self.audit = AuditLog(self.store, clock=self.clock)

    def init_project(
        self,
        *,
        name: str,
        validation_checks: tuple[ValidationCheckConfig, ...] = (),
        repair_limit: int = 3,
        execution_attempt_limit: int = 8,
    ) -> ForgeConfig:
        if self.store.is_initialized():
            self.store.ensure_layout()
            existing = self.store.load_config()
            if existing.project.name != name.strip():
                raise ForgeConflictError(
                    f"project is already initialized as {existing.project.name!r}"
                )
            return existing

        now = self.clock()
        config = ForgeConfig(
            project=ForgeProject.create(name=name, root=self.store.project_root, created_at=now),
            validation_checks=validation_checks,
            repair_limit=repair_limit,
            execution_attempt_limit=execution_attempt_limit,
        )
        self.store.initialize(config)
        self.store.write_record(
            "protocol.json",
            {
                "schema_version": 1,
                "protocol_version": CURRENT_PROTOCOL_VERSION,
                "updated_at": now,
            },
        )
        self.audit.append(
            "project.initialized",
            actor=AuditActor.system,
            payload={"project_id": config.project.id, "project_name": config.project.name},
        )
        return config

    def config(self) -> ForgeConfig:
        return self.store.load_config()

    def create_task(
        self,
        *,
        title: str,
        task_type: TaskType,
        objective: str,
        acceptance_criteria: tuple[str, ...],
        priority: TaskPriority = TaskPriority.normal,
        risk: TaskRisk = TaskRisk.medium,
        constraints: tuple[str, ...] = (),
        related_modules: tuple[str, ...] = (),
        actor: AuditActor = AuditActor.human,
    ) -> ForgeTask:
        config = self.config()
        task = ForgeTask.create(
            task_id=self.store.allocate_task_id(config.task_prefix),
            title=title,
            task_type=task_type,
            objective=objective,
            acceptance_criteria=acceptance_criteria,
            created_at=self.clock(),
            priority=priority,
            risk=risk,
            constraints=constraints,
            related_modules=related_modules,
        )
        self.store.save_new_task(task)
        self.audit.append(
            "task.created",
            actor=actor,
            task_id=task.id,
            payload={"revision": task.revision, "status": task.status.value},
        )
        return task

    def task(self, task_id: str) -> ForgeTask:
        return self.store.load_task(task_id)

    def tasks(self) -> tuple[ForgeTask, ...]:
        """Return all persisted tasks in stable identifier order."""

        return self.store.list_tasks()

    def transition_task(
        self,
        task_id: str,
        target: TaskStatus,
        *,
        expected_revision: int,
        reason: str,
        actor: AuditActor,
    ) -> ForgeTask:
        current = self.task(task_id)
        if current.revision != expected_revision:
            raise ForgeConflictError(
                f"task {task_id} revision changed: expected {expected_revision}, "
                f"found {current.revision}"
            )
        updated = TaskStateMachine.transition(
            current,
            target,
            changed_at=self.clock(),
            reason=reason,
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "task.transitioned",
            actor=actor,
            task_id=task_id,
            payload={
                "from": current.status.value,
                "to": updated.status.value,
                "reason": reason,
                "revision": updated.revision,
            },
        )
        return updated

    def record_codex_turn(
        self,
        task_id: str,
        *,
        expected_revision: int,
        thread_id: str,
        turn_id: str,
        runtime_status: str,
    ) -> ForgeTask:
        current = self._task_at_revision(task_id, expected_revision)
        if current.status not in {TaskStatus.implementing, TaskStatus.repairing}:
            raise ForgeConflictError(
                f"cannot attach Codex turn while task is {current.status.value}"
            )
        if current.codex_thread_id is not None and current.codex_thread_id != thread_id:
            raise ForgeConflictError(
                f"task {task_id} is already associated with a different Codex thread"
            )
        updated = replace(
            current,
            codex_thread_id=thread_id,
            last_turn_id=turn_id,
            updated_at=self.clock(),
            revision=current.revision + 1,
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "codex.turn.recorded",
            actor=AuditActor.system,
            task_id=task_id,
            payload={
                "thread_id": thread_id,
                "turn_id": turn_id,
                "runtime_status": runtime_status,
                "revision": updated.revision,
            },
        )
        return updated

    def replace_missing_codex_thread(
        self,
        task_id: str,
        *,
        expected_revision: int,
        previous_thread_id: str,
        thread_id: str,
        turn_id: str,
    ) -> ForgeTask:
        """Rebind a Task only after Codex confirms the previous rollout is missing."""

        current = self._task_at_revision(task_id, expected_revision)
        if current.status not in {TaskStatus.implementing, TaskStatus.repairing}:
            raise ForgeConflictError(
                f"cannot replace Codex thread while task is {current.status.value}"
            )
        if current.codex_thread_id != previous_thread_id or previous_thread_id == thread_id:
            raise ForgeConflictError(f"task {task_id} Codex thread replacement is inconsistent")
        updated = replace(
            current,
            codex_thread_id=thread_id,
            last_turn_id=turn_id,
            updated_at=self.clock(),
            revision=current.revision + 1,
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "codex.thread.replaced",
            actor=AuditActor.system,
            task_id=task_id,
            payload={
                "previous_thread_id": previous_thread_id,
                "thread_id": thread_id,
                "turn_id": turn_id,
                "reason": "rollout_missing",
                "revision": updated.revision,
            },
        )
        return updated

    def apply_validation(
        self,
        task_id: str,
        evidence: ValidationEvidence,
        *,
        expected_revision: int,
    ) -> ForgeTask:
        current = self._task_at_revision(task_id, expected_revision)
        if current.status is not TaskStatus.validating:
            raise ForgeConflictError(
                f"validation evidence requires VALIDATING, found {current.status.value}"
            )
        with_evidence = replace(current, validation=evidence)
        if evidence.passed:
            target = TaskStatus.reviewing
        elif current.repair_attempts >= self.config().repair_limit:
            target = TaskStatus.blocked
        else:
            target = TaskStatus.repairing
        updated = TaskStateMachine.transition(
            with_evidence,
            target,
            changed_at=self.clock(),
            reason=f"validation report {evidence.report_id}",
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "validation.completed",
            actor=AuditActor.validation,
            task_id=task_id,
            payload={
                "report_id": evidence.report_id,
                "passed": evidence.passed,
                "regression_report_id": evidence.regression_report_id,
                "next_status": updated.status.value,
                "revision": updated.revision,
            },
        )
        return updated

    def apply_review(
        self,
        task_id: str,
        evidence: ReviewEvidence,
        *,
        expected_revision: int,
    ) -> ForgeTask:
        current = self._task_at_revision(task_id, expected_revision)
        if current.status is not TaskStatus.reviewing:
            raise ForgeConflictError(
                f"review evidence requires REVIEWING, found {current.status.value}"
            )
        validate_human_authority(evidence.reviewer, "review approval")
        validate_review_evidence(evidence)
        if evidence.approved and (
            current.validation is None or current.validation.regression_report_id is None
        ):
            raise ForgeConflictError("approved Review requires linked L4 regression evidence")
        with_evidence = replace(current, review=evidence)
        if evidence.approved:
            target = TaskStatus.accepting
        elif current.repair_attempts >= self.config().repair_limit:
            target = TaskStatus.blocked
        else:
            target = TaskStatus.repairing
        updated = TaskStateMachine.transition(
            with_evidence,
            target,
            changed_at=self.clock(),
            reason=f"review by {evidence.reviewer}",
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "review.completed",
            actor=AuditActor.reviewer,
            task_id=task_id,
            payload={
                "approved": evidence.approved,
                "reviewer": evidence.reviewer,
                "next_status": updated.status.value,
                "revision": updated.revision,
            },
        )
        return updated

    def apply_acceptance(
        self,
        task_id: str,
        evidence: AcceptanceEvidence,
        *,
        expected_revision: int,
        task_report_id: str,
    ) -> ForgeTask:
        current = self._task_at_revision(task_id, expected_revision)
        if current.status is not TaskStatus.accepting:
            raise ForgeConflictError(
                f"acceptance evidence requires ACCEPTING, found {current.status.value}"
            )
        validate_human_authority(evidence.accepted_by, "task acceptance")
        validate_acceptance_evidence(current.acceptance_criteria, evidence)
        if not task_report_id.strip():
            raise ForgeConflictError("DONE requires a persisted Forge Task Report")
        with_evidence = replace(
            current,
            acceptance=evidence,
            task_report_id=task_report_id,
        )
        updated = TaskStateMachine.transition(
            with_evidence,
            TaskStatus.done,
            changed_at=self.clock(),
            reason=f"accepted by {evidence.accepted_by}",
        )
        self.store.save_task(updated, expected_revision=expected_revision)
        self.audit.append(
            "task.accepted",
            actor=AuditActor.human,
            task_id=task_id,
            payload={
                "accepted_by": evidence.accepted_by,
                "task_report_id": task_report_id,
                "revision": updated.revision,
            },
        )
        return updated

    def _task_at_revision(self, task_id: str, expected_revision: int) -> ForgeTask:
        current = self.task(task_id)
        if current.revision != expected_revision:
            raise ForgeConflictError(
                f"task {task_id} revision changed: expected {expected_revision}, "
                f"found {current.revision}"
            )
        return current


def utc_now() -> str:
    """Return a stable UTC timestamp for persisted Forge objects."""

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
