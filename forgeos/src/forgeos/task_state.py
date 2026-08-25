"""ForgeTask state machine and evidence gates."""

from __future__ import annotations

from dataclasses import replace

from .errors import InvalidTransitionError
from .models import ForgeTask, TaskStatus

_TERMINAL = {TaskStatus.done, TaskStatus.failed, TaskStatus.cancelled}

_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.created: frozenset({TaskStatus.analyzing}),
    TaskStatus.analyzing: frozenset({TaskStatus.planned}),
    TaskStatus.planned: frozenset({TaskStatus.implementing}),
    TaskStatus.implementing: frozenset({TaskStatus.validating}),
    TaskStatus.validating: frozenset({TaskStatus.repairing, TaskStatus.reviewing}),
    TaskStatus.repairing: frozenset({TaskStatus.validating}),
    TaskStatus.reviewing: frozenset({TaskStatus.repairing, TaskStatus.accepting}),
    TaskStatus.accepting: frozenset({TaskStatus.repairing, TaskStatus.done}),
    TaskStatus.blocked: frozenset(),
    TaskStatus.done: frozenset(),
    TaskStatus.failed: frozenset(),
    TaskStatus.cancelled: frozenset(),
}


class TaskStateMachine:
    """Validate and apply every authoritative ForgeTask status change."""

    @staticmethod
    def transition(
        task: ForgeTask,
        target: TaskStatus,
        *,
        changed_at: str,
        reason: str,
    ) -> ForgeTask:
        if not reason.strip():
            raise InvalidTransitionError("transition reason must not be empty")
        if task.status in _TERMINAL:
            raise InvalidTransitionError(f"terminal task {task.status.value} cannot transition")

        if target is TaskStatus.blocked:
            if task.status is TaskStatus.blocked:
                raise InvalidTransitionError("task is already BLOCKED")
            return replace(
                task,
                status=target,
                blocked_from=task.status,
                updated_at=changed_at,
                revision=task.revision + 1,
            )

        if target in {TaskStatus.failed, TaskStatus.cancelled}:
            return replace(
                task,
                status=target,
                blocked_from=None,
                updated_at=changed_at,
                revision=task.revision + 1,
            )

        if task.status is TaskStatus.blocked:
            if target is not task.blocked_from:
                expected = task.blocked_from.value if task.blocked_from else "<missing>"
                raise InvalidTransitionError(
                    f"BLOCKED task can only resume to {expected}, not {target.value}"
                )
        elif target not in _TRANSITIONS[task.status]:
            raise InvalidTransitionError(
                f"invalid transition {task.status.value} -> {target.value}"
            )

        TaskStateMachine._check_evidence(task, target)
        repair_attempts = (
            task.repair_attempts + 1 if target is TaskStatus.repairing else task.repair_attempts
        )
        return replace(
            task,
            status=target,
            blocked_from=None,
            updated_at=changed_at,
            revision=task.revision + 1,
            repair_attempts=repair_attempts,
        )

    @staticmethod
    def _check_evidence(task: ForgeTask, target: TaskStatus) -> None:
        if target in {TaskStatus.reviewing, TaskStatus.accepting, TaskStatus.done}:
            if task.validation is None or not task.validation.passed:
                raise InvalidTransitionError(f"{target.value} requires passing validation evidence")
        if target in {TaskStatus.accepting, TaskStatus.done}:
            if task.validation is None or task.validation.regression_report_id is None:
                raise InvalidTransitionError(
                    f"{target.value} requires linked L4 regression evidence"
                )
            if task.review is None or not task.review.passed:
                raise InvalidTransitionError(f"{target.value} requires approved review evidence")
        if target is TaskStatus.done:
            if task.acceptance is None or not task.acceptance.passed:
                raise InvalidTransitionError("DONE requires passing criterion acceptance evidence")
            if task.task_report_id is None:
                raise InvalidTransitionError("DONE requires a persisted Forge Task Report")
