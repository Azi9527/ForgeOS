"""Minimal ForgeOS execution, validation, review, and acceptance workflow."""

from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditActor
from .budget import BudgetService
from .errors import ForgeBudgetError, ForgeValidationError
from .execution import ForgeExecutionService
from .governance import (
    AcceptanceCriterionEvidence,
    AcceptanceEvidence,
    ReviewChecklistItem,
    ReviewEvidence,
    validate_acceptance_evidence,
)
from .memory import MemoryKind, MemoryService
from .models import ForgeTask, TaskStatus, ValidationEvidence
from .policy import PolicyEngine
from .recovery import CancellationService
from .regression import RegressionReport, RegressionService, ValidationReportRepository
from .service import ForgeService
from .task_report import TaskReportService
from .validation import ValidationReport, ValidationRunner
from .validation_types import ValidationPurpose


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Current task projection and optional validation evidence."""

    task: ForgeTask
    validation_report: ValidationReport | None = None
    regression_report: RegressionReport | None = None


class ForgeWorkflowService:
    """Drive the V1 single-agent workflow without delegating authority to Codex."""

    def __init__(
        self,
        forge: ForgeService,
        execution: ForgeExecutionService,
        validation: ValidationRunner,
    ) -> None:
        self.forge = forge
        self.execution = execution
        self.validation = validation
        self.validation_reports = ValidationReportRepository(forge.store)
        self.regression = RegressionService(forge.store, clock=forge.clock)
        self.task_reports = TaskReportService(forge.store, clock=forge.clock)
        self.memory = MemoryService(forge.store, clock=forge.clock)
        self.policy = PolicyEngine(forge.store, clock=forge.clock)
        self.budget = BudgetService(forge.store, clock=forge.clock)
        self.cancellations = CancellationService(forge.store, clock=forge.clock)

    def run_and_validate(self, task_id: str, *, prompt: str | None = None) -> WorkflowResult:
        task = self.forge.task(task_id)
        if self.cancellations.pending(task.id) is not None:
            cancelled = self.cancellations.apply(self.forge, task)
            if cancelled is None:
                raise ValueError(f"task {task.id} cancellation could not be applied")
            return WorkflowResult(task=cancelled)
        try:
            self.budget.enforce(task)
        except ForgeBudgetError:
            if task.status is not TaskStatus.blocked:
                self.forge.transition_task(
                    task.id,
                    TaskStatus.blocked,
                    expected_revision=task.revision,
                    reason="execution attempt budget exhausted",
                    actor=AuditActor.system,
                )
            raise
        self.policy.enforce_task(task, self.forge.config().validation_checks)
        self._ensure_baseline(task_id)
        task = self.execution.run_task(task_id, prompt=prompt)
        if task.status is not TaskStatus.validating:
            return WorkflowResult(task=task)

        return self.validate(task.id)

    def validate(self, task_id: str) -> WorkflowResult:
        """Run independent validation for a task already waiting at the gate."""

        task = self.forge.task(task_id)
        if task.status is TaskStatus.blocked and task.blocked_from is TaskStatus.validating:
            task = self.forge.transition_task(
                task.id,
                TaskStatus.validating,
                expected_revision=task.revision,
                reason="human requested validation retry",
                actor=AuditActor.human,
            )
        if task.status is not TaskStatus.validating:
            raise ValueError(f"task {task.id} is not waiting for validation")

        self.policy.enforce_task(task, self.forge.config().validation_checks)

        report = self.validation.run(
            task.id,
            self.forge.config().validation_checks,
            purpose=ValidationPurpose.current,
        )
        self.validation_reports.save(report)
        baseline = self.validation_reports.baseline(task.id)
        if baseline is None:
            raise ForgeValidationError(f"task {task.id} has no pre-execution validation baseline")
        regression = self.regression.compare(baseline, report)
        if self.cancellations.pending(task.id) is not None:
            cancelled = self.cancellations.apply(self.forge, task)
            if cancelled is None:
                raise ValueError(f"task {task.id} cancellation could not be applied")
            return WorkflowResult(
                task=cancelled,
                validation_report=report,
                regression_report=regression,
            )
        passed = report.passed and regression.passed
        task = self.forge.apply_validation(
            task.id,
            ValidationEvidence(
                report_id=report.report_id,
                passed=passed,
                checked_at=report.completed_at,
                regression_report_id=regression.report_id,
            ),
            expected_revision=task.revision,
        )
        if not passed:
            try:
                self.memory.create(
                    kind=MemoryKind.failure,
                    title=f"Validation failure for {task.id}",
                    body=(
                        f"Validation report {report.report_id} passed={report.passed}; "
                        f"regression report {regression.report_id} passed={regression.passed}."
                    ),
                    created_by="forgeos-system",
                    tags=("validation", "failure"),
                    related_modules=task.related_modules,
                    source_task_id=task.id,
                    source_report_id=report.report_id,
                )
            except Exception as exc:
                self.forge.audit.append(
                    "memory.generation_failed",
                    actor=AuditActor.system,
                    task_id=task.id,
                    payload={
                        "kind": "FAILURE",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
        return WorkflowResult(
            task=task,
            validation_report=report,
            regression_report=regression,
        )

    def review(
        self,
        task_id: str,
        *,
        approved: bool,
        reviewer: str,
        summary: str,
        checklist: tuple[ReviewChecklistItem, ...],
        risks: tuple[str, ...] = (),
        technical_debt: tuple[str, ...] = (),
    ) -> ForgeTask:
        task = self.forge.task(task_id)
        return self.forge.apply_review(
            task_id,
            ReviewEvidence(
                approved=approved,
                reviewer=reviewer,
                reviewed_at=self.forge.clock(),
                summary=summary,
                checklist=checklist,
                risks=risks,
                technical_debt=technical_debt,
            ),
            expected_revision=task.revision,
        )

    def accept(
        self,
        task_id: str,
        *,
        accepted_by: str,
        note: str,
        criteria: tuple[AcceptanceCriterionEvidence, ...],
    ) -> ForgeTask:
        task = self.forge.task(task_id)
        evidence = AcceptanceEvidence(
            accepted_by=accepted_by,
            accepted_at=self.forge.clock(),
            note=note,
            criteria=criteria,
        )
        validate_acceptance_evidence(task.acceptance_criteria, evidence)
        report = self.task_reports.create(task, evidence)
        accepted = self.forge.apply_acceptance(
            task_id,
            evidence,
            expected_revision=task.revision,
            task_report_id=report.report_id,
        )
        try:
            self.memory.create(
                kind=MemoryKind.task,
                title=f"Completed {accepted.id}: {accepted.title}",
                body=(
                    f"Task objective: {accepted.objective}\n"
                    f"Task Report: {report.report_id}\n"
                    f"Acceptance: {evidence.note or 'accepted with criterion evidence'}"
                ),
                created_by="forgeos-system",
                tags=("task", "completed"),
                related_modules=accepted.related_modules,
                source_task_id=accepted.id,
                source_report_id=report.report_id,
            )
        except Exception as exc:
            self.forge.audit.append(
                "memory.generation_failed",
                actor=AuditActor.system,
                task_id=accepted.id,
                payload={"kind": "TASK", "error_type": type(exc).__name__, "error": str(exc)},
            )
        return accepted

    def _ensure_baseline(self, task_id: str) -> ValidationReport:
        existing = self.validation_reports.baseline(task_id)
        if existing is not None:
            return existing
        report = self.validation.run(
            task_id,
            self.forge.config().validation_checks,
            purpose=ValidationPurpose.baseline,
        )
        self.validation_reports.save(report)
        self.forge.audit.append(
            "validation.baseline_captured",
            actor=AuditActor.validation,
            task_id=task_id,
            payload={
                "report_id": report.report_id,
                "passed": report.passed,
                "check_count": len(report.checks),
            },
        )
        return report
