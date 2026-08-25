"""Application-facing ForgeOS control API and serialized background jobs."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from ._control_payload import object_items as _object_items
from ._control_payload import optional_int as _optional_int
from ._control_payload import optional_nullable_text as _optional_nullable_text
from ._control_payload import optional_text as _optional_text
from ._control_payload import required_bool as _required_bool
from ._control_payload import required_int as _required_int
from ._control_payload import required_text as _required_text
from ._control_payload import string_items as _string_items
from ._control_payload import workflow_result as _workflow_result
from .audit import AuditActor
from .codex_sdk import CodexSdkGateway, CodexSdkSettings
from .config import ValidationCheckConfig
from .control_jobs import ControlJob, ControlJobManager, JobState
from .doctor import ForgeDoctor
from .errors import ForgeConflictError, ForgeNotFoundError
from .execution import CodexGateway, ForgeExecutionService
from .execution_events import CodexProgressEvent, CodexTurnControl
from .execution_records import ExecutionAttempt, ExecutionAttemptRepository
from .governance import AcceptanceCriterionEvidence, ReviewChecklistItem
from .memory import MemoryKind, MemoryService, MemoryStatus
from .models import TaskPriority, TaskRisk, TaskType
from .operations import ForgeOperations
from .operator import ForgeOperator
from .policy import PolicyEngine
from .regression import RegressionService, ValidationReportRepository
from .service import Clock, ForgeService, utc_now
from .task_report import TaskReportService
from .validation import ValidationRunner
from .workflow import ForgeWorkflowService

__all__ = ["ControlJob", "ForgeControlService", "JobState"]

GatewayFactory = Callable[[], CodexGateway]


class ForgeControlService:
    """Stable application boundary consumed by the local Web API."""

    def __init__(
        self,
        workspace: Path,
        *,
        gateway_factory: GatewayFactory | None = None,
        codex_settings: CodexSdkSettings | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.clock = clock or utc_now
        self.forge = ForgeService(workspace, clock=self.clock)
        settings = codex_settings or CodexSdkSettings(workspace=workspace)
        self._gateway_factory = gateway_factory or (lambda: CodexSdkGateway(settings))
        self.jobs = ControlJobManager(clock=self.clock)
        self.attempts = ExecutionAttemptRepository(self.forge.store)
        self.memory = MemoryService(self.forge.store, clock=self.clock)
        self.policy = PolicyEngine(self.forge.store, clock=self.clock)
        self._turn_lock = threading.Lock()
        self._active_turns: dict[str, tuple[str, CodexTurnControl]] = {}
        if self.forge.store.is_initialized():
            self.operations = ForgeOperations(self.forge)
            self.operations.recover()
            self.operator = ForgeOperator(self.forge)
        else:
            self.operations = None
            self.operator = None

    def close(self) -> None:
        with self._turn_lock:
            controls = tuple(control for _, control in self._active_turns.values())
        for control in controls:
            control.interrupt()
        self.jobs.close()

    def status(self) -> dict[str, Any]:
        if not self.forge.store.is_initialized():
            return {"initialized": False, "workspace": str(self.forge.store.project_root)}
        config = self.forge.config()
        tasks = self.forge.tasks()
        counts: dict[str, int] = {}
        for task in tasks:
            counts[task.status.value] = counts.get(task.status.value, 0) + 1
        return {
            "initialized": True,
            "workspace": str(self.forge.store.project_root),
            "project": config.project.to_dict(),
            "validation_checks": [check.to_dict() for check in config.validation_checks],
            "repair_limit": config.repair_limit,
            "task_count": len(tasks),
            "tasks_by_status": counts,
            "operations": self._require_operations().status(),
            "operator": self._require_operator().status(),
        }

    def initialize(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        checks_value = payload.get("validation_checks", [])
        if not isinstance(checks_value, list) or not all(
            isinstance(check, dict) for check in checks_value
        ):
            raise ValueError("validation_checks must be an array of objects")
        checks = tuple(ValidationCheckConfig.from_dict(check) for check in checks_value)
        config = self.forge.init_project(
            name=_required_text(payload, "name"),
            validation_checks=checks,
            repair_limit=_optional_int(payload, "repair_limit", default=3),
            execution_attempt_limit=_optional_int(payload, "execution_attempt_limit", default=8),
        )
        self.operations = ForgeOperations(self.forge)
        self.operator = ForgeOperator(self.forge)
        return config.to_dict()

    def list_tasks(self) -> dict[str, Any]:
        return {"tasks": [task.to_dict() for task in self.forge.tasks()]}

    def create_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        task = self.forge.create_task(
            title=_required_text(payload, "title"),
            task_type=TaskType(_required_text(payload, "task_type")),
            objective=_required_text(payload, "objective"),
            acceptance_criteria=_string_items(payload, "acceptance_criteria", required=True),
            priority=TaskPriority(_optional_text(payload, "priority", default="NORMAL")),
            risk=TaskRisk(_optional_text(payload, "risk", default="MEDIUM")),
            constraints=_string_items(payload, "constraints"),
            related_modules=_string_items(payload, "related_modules"),
        )
        return task.to_dict()

    def task_detail(self, task_id: str) -> dict[str, Any]:
        task = self.forge.task(task_id)
        events = [
            event.to_dict() for event in self.forge.audit.read_all() if event.task_id == task_id
        ]
        executions = sorted(
            self.forge.store.list_records(f"executions/{task_id}"),
            key=lambda record: (
                record["started_at"] if isinstance(record.get("started_at"), int) else -1,
                str(record.get("turn_id", "")),
            ),
        )
        attempts = [attempt.to_dict() for attempt in self.attempts.list_for_task(task_id)]
        git_snapshots = _chronological_records(
            self.forge.store.list_records(f"evidence/git/{task_id}"),
            timestamp_field="captured_at",
            identifier_field="snapshot_id",
        )
        contexts = _chronological_records(
            self.forge.store.list_records(f"context/packages/{task_id}"),
            timestamp_field="created_at",
            identifier_field="package_id",
        )
        memory_selections = _chronological_records(
            self.forge.store.list_records(f"memory/selections/{task_id}"),
            timestamp_field="created_at",
            identifier_field="selection_id",
        )
        memories = [
            item.to_dict()
            for item in self.memory.list()
            if item.source_task_id == task_id
            or any(
                selection.get("memory_id") == item.id
                for record in memory_selections
                for selection in record.get("items", [])
                if isinstance(selection, dict)
            )
        ]
        policy_evaluations = _chronological_records(
            self.policy.evaluations(task_id),
            timestamp_field="evaluated_at",
            identifier_field="id",
        )
        validations = _chronological_records(
            (
                report
                for report in self.forge.store.list_records("validation/results")
                if report.get("task_id") == task_id
            ),
            timestamp_field="started_at",
            identifier_field="report_id",
        )
        baseline = ValidationReportRepository(self.forge.store).baseline(task_id)
        regressions = _chronological_records(
            (
                report.to_dict()
                for report in RegressionService(self.forge.store, clock=self.clock).for_task(
                    task_id
                )
            ),
            timestamp_field="completed_at",
            identifier_field="report_id",
        )
        reports = _chronological_records(
            (
                report.to_dict()
                for report in TaskReportService(self.forge.store, clock=self.clock).for_task(
                    task_id
                )
            ),
            timestamp_field="generated_at",
            identifier_field="report_id",
        )
        jobs = [job.to_dict() for job in self.jobs.list() if job.task_id == task_id]
        operational_evidence = self._require_operations().task_evidence(task_id)
        operational_evidence["budgets"] = _chronological_records(
            operational_evidence["budgets"],
            timestamp_field="evaluated_at",
            identifier_field="id",
        )
        operational_evidence["recovery_runs"] = _chronological_records(
            operational_evidence["recovery_runs"],
            timestamp_field="recovered_at",
            identifier_field="id",
        )
        return {
            "task": task.to_dict(),
            "audit": events,
            "executions": executions,
            "attempts": attempts,
            "git": git_snapshots,
            "contexts": contexts,
            "memory_selections": memory_selections,
            "memories": memories,
            "policy_evaluations": policy_evaluations,
            "validations": validations,
            "validation_baseline": baseline.to_dict() if baseline is not None else None,
            "regressions": regressions,
            "reports": reports,
            "jobs": jobs,
            **operational_evidence,
        }

    def audit_events(
        self,
        *,
        task_id: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._require_operator().audit_query(
            task_id=task_id,
            event_type=event_type,
            actor=actor,
            after_sequence=after_sequence,
            limit=limit,
        )

    def operator_status(self) -> dict[str, Any]:
        return self._require_operator().status()

    def release_check(self) -> dict[str, Any]:
        return self._require_operator().release_check()

    def list_policies(self) -> dict[str, Any]:
        return self._require_operator().list_policies()

    def create_policy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._require_operator().create_policy(payload)

    def retire_policy(self, rule_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._require_operator().retire_policy(rule_id, payload)

    def list_memories(self, status: str | None = None) -> dict[str, Any]:
        parsed = MemoryStatus(status) if status is not None else None
        return {"memories": [item.to_dict() for item in self.memory.list(status=parsed)]}

    def create_memory(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.memory.create(
            kind=MemoryKind(_required_text(payload, "kind")),
            title=_required_text(payload, "title"),
            body=_required_text(payload, "body"),
            created_by=_required_text(payload, "created_by"),
            tags=_string_items(payload, "tags"),
            related_modules=_string_items(payload, "related_modules"),
            source_task_id=_optional_nullable_text(payload, "source_task_id"),
            source_report_id=_optional_nullable_text(payload, "source_report_id"),
        ).to_dict()

    def decide_memory(
        self, memory_id: str, payload: Mapping[str, Any], *, accepted: bool
    ) -> dict[str, Any]:
        return self.memory.decide(
            memory_id,
            accepted=accepted,
            decided_by=_required_text(payload, "decided_by"),
            reason=_required_text(payload, "reason"),
            expected_revision=_required_int(payload, "expected_revision"),
        ).to_dict()

    def policy_check(self, task_id: str) -> dict[str, Any]:
        task = self.forge.task(task_id)
        return self.policy.enforce_task(task, self.forge.config().validation_checks).to_dict()

    def cancel(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        operations = self._require_operations()
        request = operations.request_cancellation(
            task_id,
            requested_by=_required_text(payload, "requested_by"),
            reason=_required_text(payload, "reason"),
        )
        with self._turn_lock:
            active = self._active_turns.get(task_id)
        active_job = next(
            (
                job
                for job in self.jobs.list()
                if job.task_id == task_id and job.state in {JobState.queued, JobState.running}
            ),
            None,
        )
        runtime = None
        if active is not None:
            attempt_id, control = active
            attempt = self.attempts.load(task_id, attempt_id)
            self.attempts.request_interrupt(attempt)
            runtime = control.interrupt()
        elif active_job is None:
            return {"request": request, "task": operations.apply_cancellation(task_id)}
        return {"request": request, "task": None, "runtime": runtime}

    def operations_status(self) -> dict[str, Any]:
        return self._require_operations().status()

    def integrity_scan(self) -> dict[str, Any]:
        return self._require_operations().integrity_scan()

    def migration_status(self) -> dict[str, Any]:
        return self._require_operations().migration_status()

    def migration_apply(self) -> dict[str, Any]:
        return self._require_operations().migration_apply()

    def recover(self) -> dict[str, Any]:
        return self._require_operations().recover()

    def task_report(self, task_id: str) -> dict[str, Any]:
        reports = TaskReportService(self.forge.store, clock=self.clock).for_task(task_id)
        if not reports:
            raise ForgeNotFoundError(f"task has no Forge Task Report: {task_id}")
        return reports[-1].to_dict()

    def doctor(self) -> dict[str, Any]:
        return ForgeDoctor(self.forge.store.project_root).run().to_dict()

    def diagnostic_bundle(self) -> dict[str, Any]:
        """Return bounded operator diagnostics without credentials or model content."""

        return {
            "schema_version": 1,
            "generated_at": self.clock(),
            "status": self.status(),
            "doctor": self.doctor(),
            "recent_jobs": [
                {
                    "id": job.id,
                    "kind": job.kind,
                    "task_id": job.task_id,
                    "state": job.state.value,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                }
                for job in self.jobs.list()[:20]
            ],
        }

    def submit_run(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        self.forge.task(task_id)
        prompt = _optional_nullable_text(payload, "prompt")
        job = self.jobs.submit(
            "run",
            task_id,
            lambda job_id: self._run_and_validate(job_id, task_id, prompt),
        )
        self._audit_job(job, "control.job.queued")
        return job.to_dict()

    def submit_validation(self, task_id: str) -> dict[str, Any]:
        self.forge.task(task_id)
        job = self.jobs.submit("validate", task_id, lambda _job_id: self._validate(task_id))
        self._audit_job(job, "control.job.queued")
        return job.to_dict()

    def review(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        workflow = self._workflow(_UnavailableGateway())
        task = workflow.review(
            task_id,
            approved=_required_bool(payload, "approved"),
            reviewer=_required_text(payload, "reviewer"),
            summary=_optional_text(payload, "summary", default=""),
            checklist=tuple(
                ReviewChecklistItem.from_dict(item)
                for item in _object_items(payload, "checklist", required=True)
            ),
            risks=_string_items(payload, "risks"),
            technical_debt=_string_items(payload, "technical_debt"),
        )
        return task.to_dict()

    def accept(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        workflow = self._workflow(_UnavailableGateway())
        task = workflow.accept(
            task_id,
            accepted_by=_required_text(payload, "accepted_by"),
            note=_optional_text(payload, "note", default=""),
            criteria=tuple(
                AcceptanceCriterionEvidence.from_dict(item)
                for item in _object_items(payload, "criteria", required=True)
            ),
        )
        return task.to_dict()

    def interrupt(self, task_id: str) -> dict[str, Any]:
        with self._turn_lock:
            active = self._active_turns.get(task_id)
        if active is None:
            raise ForgeConflictError(f"task {task_id} has no active Codex turn")
        attempt_id, control = active
        attempt = self.attempts.load(task_id, attempt_id)
        attempt = self.attempts.request_interrupt(attempt)
        result = control.interrupt()
        self.forge.audit.append(
            "codex.turn.interrupt_requested",
            actor=AuditActor.human,
            task_id=task_id,
            payload={
                "attempt_id": attempt.id,
                "thread_id": control.thread_id,
                "turn_id": control.turn_id,
            },
        )
        return {"attempt": attempt.to_dict(), "runtime": result}

    def steer(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        input_text = _required_text(payload, "input")
        with self._turn_lock:
            active = self._active_turns.get(task_id)
        if active is None:
            raise ForgeConflictError(f"task {task_id} has no active Codex turn")
        attempt_id, control = active
        result = control.steer(input_text)
        self.forge.audit.append(
            "codex.turn.steered",
            actor=AuditActor.human,
            task_id=task_id,
            payload={
                "attempt_id": attempt_id,
                "turn_id": control.turn_id,
                "input_sha256": __import__("hashlib").sha256(input_text.encode()).hexdigest(),
                "input_bytes": len(input_text.encode("utf-8")),
            },
        )
        return {"attempt_id": attempt_id, "runtime": result}

    def _run_and_validate(
        self,
        job_id: str,
        task_id: str,
        prompt: str | None,
    ) -> dict[str, Any]:
        gateway = self._gateway_factory()
        try:
            result = self._workflow(
                gateway,
                on_progress=lambda attempt, event: self._on_progress(job_id, attempt, event),
                on_started=lambda attempt, control: self._on_started(
                    job_id, task_id, attempt, control
                ),
            ).run_and_validate(task_id, prompt=prompt)
            return _workflow_result(result)
        finally:
            with self._turn_lock:
                self._active_turns.pop(task_id, None)
            close = getattr(gateway, "close", None)
            if callable(close):
                close()

    def _validate(self, task_id: str) -> dict[str, Any]:
        return _workflow_result(self._workflow(_UnavailableGateway()).validate(task_id))

    def _workflow(
        self,
        gateway: CodexGateway,
        *,
        on_progress: Any = None,
        on_started: Any = None,
        developer_instructions: str | None = None,
    ) -> ForgeWorkflowService:
        execution = ForgeExecutionService(
            self.forge,
            gateway,
            on_progress=on_progress,
            on_started=on_started,
            developer_instructions=developer_instructions,
        )
        validation = ValidationRunner(self.forge.store.project_root, clock=self.clock)
        return ForgeWorkflowService(self.forge, execution, validation)

    def _on_started(
        self,
        job_id: str,
        task_id: str,
        attempt: ExecutionAttempt,
        control: CodexTurnControl,
    ) -> None:
        with self._turn_lock:
            self._active_turns[task_id] = (attempt.id, control)
        self.jobs.update_progress(
            job_id,
            {
                "phase": "started",
                "attempt_id": attempt.id,
                "thread_id": control.thread_id,
                "turn_id": control.turn_id,
            },
        )

    def _on_progress(
        self,
        job_id: str,
        attempt: ExecutionAttempt,
        event: CodexProgressEvent,
    ) -> None:
        self.jobs.update_progress(
            job_id,
            {
                "attempt_id": attempt.id,
                "event": event.to_dict(),
            },
        )

    def _audit_job(self, job: ControlJob, event_type: str) -> None:
        self.forge.audit.append(
            event_type,
            actor=AuditActor.system,
            task_id=job.task_id,
            payload={"job_id": job.id, "kind": job.kind, "state": job.state.value},
        )

    def _require_operations(self) -> ForgeOperations:
        if self.operations is None:
            raise ForgeNotFoundError("ForgeOS project is not initialized")
        return self.operations

    def _require_operator(self) -> ForgeOperator:
        if self.operator is None:
            raise ForgeNotFoundError("ForgeOS project is not initialized")
        return self.operator


class _UnavailableGateway:
    def run_turn(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Codex gateway is unavailable for this control operation")


def _chronological_records(
    records: Iterable[dict[str, Any]],
    *,
    timestamp_field: str,
    identifier_field: str,
) -> list[dict[str, Any]]:
    return sorted(
        records,
        key=lambda record: (
            str(record.get(timestamp_field, "")),
            str(record.get(identifier_field, "")),
        ),
    )
