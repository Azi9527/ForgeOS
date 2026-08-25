"""ForgeTask orchestration over the Codex Python SDK boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol

from .audit import AuditActor
from .budget import BudgetService
from .codex_sdk import CodexTurnResult
from .context import ContextPackage, ContextPackageBuilder
from .errors import ForgeConflictError
from .execution_events import CodexProgressEvent, CodexTurnControl
from .execution_records import (
    AttemptState,
    ExecutionAttempt,
    ExecutionAttemptRepository,
    ExecutionStepResult,
    StepState,
)
from .git_evidence import GitEvidenceService, GitSnapshot
from .model_input import MODEL_ITEM_BYTE_LIMIT, ModelInput, assemble_turn_input, bounded_model_text
from .models import ForgeTask, TaskStatus
from .policy import PolicyEngine
from .recovery import CancellationService
from .service import ForgeService


class CodexGateway(Protocol):
    """Minimal Codex SDK behavior required by Forge execution."""

    def run_turn(
        self,
        prompt: ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> CodexTurnResult: ...


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Bounded persisted evidence for one Codex turn."""

    task_id: str
    thread_id: str
    turn_id: str
    runtime_status: str
    prompt_sha256: str
    final_response: str | None
    error_message: str | None
    started_at: int | None
    completed_at: int | None
    duration_ms: int | None
    item_count: int
    usage: dict[str, Any] | None
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "runtime_status": self.runtime_status,
            "prompt_sha256": self.prompt_sha256,
            "final_response": self.final_response,
            "error_message": self.error_message,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "item_count": self.item_count,
            "usage": self.usage,
        }


class ForgeExecutionService:
    """Run and resume Codex turns while ForgeOS owns every task transition."""

    def __init__(
        self,
        forge: ForgeService,
        codex: CodexGateway,
        *,
        on_progress: Any = None,
        on_started: Any = None,
        developer_instructions: str | None = None,
    ) -> None:
        self.forge = forge
        self.codex = codex
        self.attempts = ExecutionAttemptRepository(forge.store)
        self.on_progress = on_progress
        self.on_started = on_started
        self.developer_instructions = developer_instructions
        self.git = GitEvidenceService(forge.store.project_root, clock=forge.clock)
        self.context = ContextPackageBuilder(forge.store, clock=forge.clock)
        self.policy = PolicyEngine(forge.store, clock=forge.clock)
        self.budget = BudgetService(forge.store, clock=forge.clock)
        self.cancellations = CancellationService(forge.store, clock=forge.clock)

    def run_task(self, task_id: str, *, prompt: str | None = None) -> ForgeTask:
        task = self.forge.task(task_id)
        pending = self.cancellations.pending(task.id)
        if pending is not None:
            cancelled = self.cancellations.apply(self.forge, task)
            if cancelled is None:
                raise ForgeConflictError(f"task {task.id} cancellation could not be applied")
            return cancelled
        self.budget.enforce(task)
        self.policy.enforce_task(task, self.forge.config().validation_checks)
        attempt = self.attempts.create(task_id=task_id, kind="run", created_at=self.forge.clock())
        attempt = self.attempts.start(attempt, started_at=self.forge.clock())
        try:
            attempt, baseline = self._capture_git(attempt, kind="baseline")
            package = self.context.build_and_store(task, baseline)
            attempt = self.attempts.append_step(attempt, _context_step(package))
            self.forge.audit.append(
                "context.package.built",
                actor=AuditActor.system,
                task_id=task.id,
                payload={
                    "context_id": package.id,
                    "content_sha256": package.content_sha256,
                    "total_bytes": package.total_bytes,
                    "truncated": package.truncated,
                },
            )
            actual_prompt = assemble_turn_input(
                task_id=task.id,
                title=task.title,
                objective=task.objective,
                acceptance_criteria=task.acceptance_criteria,
                constraints=task.constraints,
                runtime_items=package.runtime_items(),
                custom_prompt=prompt,
            )
            task = self._prepare_for_execution(task)
        except Exception as exc:
            self._record_failed_attempt(attempt, exc)
            raise

        actual_instructions = _bounded_instructions(self.developer_instructions)
        try:
            result, attempt, task = self._run_codex(
                task,
                actual_prompt,
                attempt,
                developer_instructions=actual_instructions,
            )
        except Exception as exc:
            latest = self.attempts.load(attempt.task_id, attempt.id)
            try:
                latest, _snapshot = self._capture_git(latest, kind="current")
            except Exception as git_error:
                self._audit_git_failure(task.id, git_error)
            self._record_failed_attempt(latest, exc)
            self.forge.audit.append(
                "codex.turn.failed",
                actor=AuditActor.system,
                task_id=task.id,
                payload={"error_type": type(exc).__name__, "message": str(exc)[:2_000]},
            )
            task = self.forge.task(task.id)
            if self.cancellations.pending(task.id) is not None:
                cancelled = self.cancellations.apply(self.forge, task)
                if cancelled is not None:
                    return cancelled
            self.forge.transition_task(
                task.id,
                TaskStatus.blocked,
                expected_revision=task.revision,
                reason="Codex SDK turn failed",
                actor=AuditActor.system,
            )
            raise

        attempt = self.attempts.load(attempt.task_id, attempt.id)
        step_status = StepState.completed if result.status == "completed" else StepState.interrupted
        attempt = self.attempts.append_step(
            attempt,
            ExecutionStepResult(
                name="codex_turn",
                status=step_status,
                started_at=attempt.started_at or attempt.created_at,
                finished_at=self.forge.clock(),
                input_summary={"prompt_sha256": _prompt_sha256(actual_prompt)},
                output_summary={
                    "runtime_status": result.status,
                    "item_count": len(result.items),
                    "duration_ms": result.duration_ms,
                },
                error=result.error_message,
            ),
        )
        attempt, _snapshot = self._capture_git(attempt, kind="current")
        terminal_state = (
            AttemptState.completed
            if result.status == "completed"
            else AttemptState.interrupted
            if result.status == "interrupted"
            else AttemptState.failed
        )
        attempt = self.attempts.finish(
            attempt,
            status=terminal_state,
            finished_at=self.forge.clock(),
            error=result.error_message,
        )
        record = _execution_record(task.id, actual_prompt, result)
        record_name = hashlib.sha256(result.turn_id.encode()).hexdigest()[:20]
        self.forge.store.write_record(
            f"executions/{task.id}/{record_name}.json",
            record.to_dict(),
        )
        if task.last_turn_id != result.turn_id:
            task = self.forge.record_codex_turn(
                task.id,
                expected_revision=task.revision,
                thread_id=result.thread_id,
                turn_id=result.turn_id,
                runtime_status=result.status,
            )
        else:
            self.forge.audit.append(
                "codex.turn.completed",
                actor=AuditActor.system,
                task_id=task.id,
                payload={
                    "thread_id": result.thread_id,
                    "turn_id": result.turn_id,
                    "runtime_status": result.status,
                },
            )
        if self.cancellations.pending(task.id) is not None:
            cancelled = self.cancellations.apply(self.forge, task)
            if cancelled is None:
                raise ForgeConflictError(f"task {task.id} cancellation could not be applied")
            return cancelled
        if result.status != "completed":
            return self.forge.transition_task(
                task.id,
                TaskStatus.blocked,
                expected_revision=task.revision,
                reason=f"Codex turn ended with {result.status}",
                actor=AuditActor.system,
            )
        return self.forge.transition_task(
            task.id,
            TaskStatus.validating,
            expected_revision=task.revision,
            reason="Codex turn completed; independent validation required",
            actor=AuditActor.system,
        )

    def _run_codex(
        self,
        task: ForgeTask,
        actual_prompt: ModelInput,
        attempt: ExecutionAttempt,
        *,
        developer_instructions: str | None,
    ) -> tuple[CodexTurnResult, ExecutionAttempt, ForgeTask]:
        controlled = getattr(self.codex, "run_turn_controlled", None)
        if not callable(controlled):
            result = self.codex.run_turn(actual_prompt, thread_id=task.codex_thread_id)
            attempt = self.attempts.attach_turn(
                attempt,
                thread_id=result.thread_id,
                turn_id=result.turn_id,
            )
            if result.replaced_thread_id is not None:
                task = self.forge.replace_missing_codex_thread(
                    task.id,
                    expected_revision=task.revision,
                    previous_thread_id=result.replaced_thread_id,
                    thread_id=result.thread_id,
                    turn_id=result.turn_id,
                )
            return result, attempt, task

        active_attempt = attempt
        active_task = task

        def started(control: CodexTurnControl) -> None:
            nonlocal active_attempt, active_task
            active_attempt = self.attempts.attach_turn(
                active_attempt,
                thread_id=control.thread_id,
                turn_id=control.turn_id,
            )
            if control.replaced_thread_id is None:
                active_task = self.forge.record_codex_turn(
                    active_task.id,
                    expected_revision=active_task.revision,
                    thread_id=control.thread_id,
                    turn_id=control.turn_id,
                    runtime_status="inProgress",
                )
            else:
                active_task = self.forge.replace_missing_codex_thread(
                    active_task.id,
                    expected_revision=active_task.revision,
                    previous_thread_id=control.replaced_thread_id,
                    thread_id=control.thread_id,
                    turn_id=control.turn_id,
                )
            if self.on_started is not None:
                self.on_started(active_attempt, control)

        def progress(event: CodexProgressEvent) -> None:
            if self.on_progress is not None:
                self.on_progress(active_attempt, event)

        result = controlled(
            actual_prompt,
            thread_id=task.codex_thread_id,
            developer_instructions=developer_instructions,
            on_progress=progress,
            on_started=started,
        )
        return result, active_attempt, active_task

    def _record_failed_attempt(
        self,
        attempt: ExecutionAttempt,
        error: Exception,
    ) -> ExecutionAttempt:
        latest = self.attempts.load(attempt.task_id, attempt.id)
        if latest.status.terminal:
            return latest
        latest = self.attempts.append_step(
            latest,
            ExecutionStepResult(
                name="codex_turn",
                status=StepState.failed,
                started_at=latest.started_at or latest.created_at,
                finished_at=self.forge.clock(),
                error=str(error)[:2_000],
            ),
        )
        return self.attempts.finish(
            latest,
            status=AttemptState.failed,
            finished_at=self.forge.clock(),
            error=str(error),
        )

    def _capture_git(
        self,
        attempt: ExecutionAttempt,
        *,
        kind: str,
    ) -> tuple[ExecutionAttempt, GitSnapshot]:
        snapshot = self.git.capture_and_store(
            self.forge.store,
            attempt.task_id,
            kind=kind,
        )
        return self.attempts.append_step(attempt, _git_step(snapshot)), snapshot

    def _audit_git_failure(self, task_id: str, error: Exception) -> None:
        self.forge.audit.append(
            "git.evidence.failed",
            actor=AuditActor.system,
            task_id=task_id,
            payload={"error_type": type(error).__name__, "message": str(error)[:2_000]},
        )

    def _prepare_for_execution(self, task: ForgeTask) -> ForgeTask:
        if task.status is TaskStatus.blocked:
            if task.blocked_from not in {TaskStatus.implementing, TaskStatus.repairing}:
                blocked_from = task.blocked_from.value if task.blocked_from else "unknown"
                raise ForgeConflictError(
                    f"task {task.id} was blocked from {blocked_from} and cannot resume execution"
                )
            task = self.forge.transition_task(
                task.id,
                task.blocked_from,
                expected_revision=task.revision,
                reason="human requested Codex execution retry",
                actor=AuditActor.human,
            )
        if task.status is TaskStatus.created:
            task = self.forge.transition_task(
                task.id,
                TaskStatus.analyzing,
                expected_revision=task.revision,
                reason="execution requested",
                actor=AuditActor.system,
            )
        if task.status is TaskStatus.analyzing:
            task = self.forge.transition_task(
                task.id,
                TaskStatus.planned,
                expected_revision=task.revision,
                reason="minimal V1 plan prepared",
                actor=AuditActor.system,
            )
        if task.status is TaskStatus.planned:
            task = self.forge.transition_task(
                task.id,
                TaskStatus.implementing,
                expected_revision=task.revision,
                reason="Codex implementation turn starting",
                actor=AuditActor.system,
            )
        if task.status not in {TaskStatus.implementing, TaskStatus.repairing}:
            raise ForgeConflictError(
                f"task {task.id} cannot run while status is {task.status.value}"
            )
        return task


def _execution_record(task_id: str, prompt: ModelInput, result: CodexTurnResult) -> ExecutionRecord:
    response = result.final_response
    if response is not None and len(response) > 20_000:
        response = response[:20_000] + "\n[TRUNCATED BY FORGEOS]"
    return ExecutionRecord(
        task_id=task_id,
        thread_id=result.thread_id,
        turn_id=result.turn_id,
        runtime_status=result.status,
        prompt_sha256=_prompt_sha256(prompt),
        final_response=response,
        error_message=_bounded_optional(result.error_message, maximum=2_000),
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_ms=result.duration_ms,
        item_count=len(result.items),
        usage=result.usage,
    )


def _git_step(snapshot: GitSnapshot) -> ExecutionStepResult:
    return ExecutionStepResult(
        name=f"git_{snapshot.kind}",
        status=StepState.completed,
        started_at=snapshot.captured_at,
        finished_at=snapshot.captured_at,
        output_summary={
            "snapshot_id": snapshot.id,
            "available": snapshot.available,
            "head": snapshot.head,
            "branch": snapshot.branch,
            "dirty": snapshot.dirty,
            "changed_file_count": len(snapshot.changed_files),
            "status_sha256": snapshot.status_sha256,
            "diff_sha256": snapshot.diff_sha256,
            "warning": snapshot.warning,
        },
        files_changed=snapshot.changed_files,
    )


def _context_step(package: ContextPackage) -> ExecutionStepResult:
    return ExecutionStepResult(
        name="context_package",
        status=StepState.completed,
        started_at=package.created_at,
        finished_at=package.created_at,
        output_summary={
            "context_id": package.id,
            "content_sha256": package.content_sha256,
            "total_bytes": package.total_bytes,
            "truncated": package.truncated,
            "fragment_count": len(package.fragments),
            "rule_resolution_sha256": package.rule_resolution_sha256,
            "git_snapshot_id": package.git_snapshot_id,
            "memory_selection_id": package.memory_selection_id,
        },
    )


def _bounded_instructions(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return bounded_model_text(value.strip(), maximum_bytes=MODEL_ITEM_BYTE_LIMIT)


def _prompt_sha256(prompt: ModelInput) -> str:
    return hashlib.sha256(prompt.canonical_bytes()).hexdigest()


def _bounded_optional(value: str | None, *, maximum: int) -> str | None:
    if value is None or len(value) <= maximum:
        return value
    return value[:maximum] + "\n[TRUNCATED BY FORGEOS]"
