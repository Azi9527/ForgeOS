"""Persistent final Forge Task Report assembled only from authoritative evidence."""

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .errors import ForgeConflictError
from .governance import (
    AcceptanceEvidence,
    validate_acceptance_evidence,
    validate_human_authority,
)
from .models import ForgeTask, TaskStatus
from .regression import RegressionReport, RegressionService, ValidationReportRepository
from .storage import ForgeStore
from .validation_types import ValidationLevel, ValidationReport


@dataclass(frozen=True, slots=True)
class TaskReport:
    """Requirements-level Task Report with references to source evidence."""

    report_id: str
    task_id: str
    objective: str
    status: str
    generated_at: str
    changed_files: tuple[str, ...]
    commands: tuple[dict[str, Any], ...]
    build_result: tuple[dict[str, Any], ...]
    test_result: tuple[dict[str, Any], ...]
    regression_result: dict[str, Any]
    review: dict[str, Any]
    acceptance: dict[str, Any]
    repair_attempts: int
    risks: tuple[str, ...]
    technical_debt: tuple[str, ...]
    final_diff: dict[str, Any]
    start_commit: str | None
    end_commit: str | None
    validation_report_id: str
    regression_report_id: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "task_id": self.task_id,
            "objective": self.objective,
            "status": self.status,
            "generated_at": self.generated_at,
            "changed_files": list(self.changed_files),
            "commands": list(self.commands),
            "build_result": list(self.build_result),
            "test_result": list(self.test_result),
            "regression_result": self.regression_result,
            "review": self.review,
            "acceptance": self.acceptance,
            "repair_attempts": self.repair_attempts,
            "risks": list(self.risks),
            "technical_debt": list(self.technical_debt),
            "final_diff": self.final_diff,
            "start_commit": self.start_commit,
            "end_commit": self.end_commit,
            "validation_report_id": self.validation_report_id,
            "regression_report_id": self.regression_report_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskReport":
        if value.get("schema_version") != 1:
            raise ValueError(f"unsupported Task Report schema: {value.get('schema_version')!r}")
        return cls(
            report_id=_text(value, "report_id"),
            task_id=_text(value, "task_id"),
            objective=_text(value, "objective"),
            status=_text(value, "status"),
            generated_at=_text(value, "generated_at"),
            changed_files=_strings(value, "changed_files"),
            commands=_objects(value, "commands"),
            build_result=_objects(value, "build_result"),
            test_result=_objects(value, "test_result"),
            regression_result=_object(value, "regression_result"),
            review=_object(value, "review"),
            acceptance=_object(value, "acceptance"),
            repair_attempts=_integer(value, "repair_attempts"),
            risks=_strings(value, "risks"),
            technical_debt=_strings(value, "technical_debt"),
            final_diff=_object(value, "final_diff"),
            start_commit=_optional_text(value, "start_commit"),
            end_commit=_optional_text(value, "end_commit"),
            validation_report_id=_text(value, "validation_report_id"),
            regression_report_id=_text(value, "regression_report_id"),
        )


class TaskReportService:
    """Build and persist a report without trusting model-authored completion claims."""

    def __init__(self, store: ForgeStore, *, clock: Any) -> None:
        self.store = store
        self.clock = clock
        self.validations = ValidationReportRepository(store)
        self.regressions = RegressionService(store, clock=clock)

    def create(self, task: ForgeTask, acceptance: AcceptanceEvidence) -> TaskReport:
        if task.status is not TaskStatus.accepting:
            raise ForgeConflictError("Task Report can only be generated at ACCEPTING")
        validate_acceptance_evidence(task.acceptance_criteria, acceptance)
        validate_human_authority(acceptance.accepted_by, "task acceptance")
        validation = self._latest_validation(task)
        required_levels = {
            check.level for check in validation.checks if check.required and check.passed
        }
        if ValidationLevel.build not in required_levels:
            raise ForgeConflictError("Task Report requires passing L1 Build evidence")
        if not required_levels.intersection({ValidationLevel.unit, ValidationLevel.integration}):
            raise ForgeConflictError(
                "Task Report requires passing L2 Unit or L3 Integration evidence"
            )
        regression = self._latest_regression(task, validation)
        if task.review is None or not task.review.passed:
            raise ForgeConflictError("Task Report requires passing structured Review")
        validate_human_authority(task.review.reviewer, "review approval")
        git = self.store.list_records(f"evidence/git/{task.id}")
        baselines = [item for item in git if item.get("kind") == "baseline"]
        currents = [item for item in git if item.get("kind") == "current"]
        baseline = baselines[-1] if baselines else {}
        current = currents[-1] if currents else {}
        commands = tuple(_command_projection(check) for check in validation.checks)
        report = TaskReport(
            report_id=f"task-report-{uuid4()}",
            task_id=task.id,
            objective=task.objective,
            status="DONE",
            generated_at=self.clock(),
            changed_files=tuple(str(item) for item in current.get("changed_files", [])),
            commands=commands,
            build_result=tuple(
                command for command in commands if command["level"] == ValidationLevel.build.value
            ),
            test_result=tuple(
                command
                for command in commands
                if command["level"]
                in {ValidationLevel.unit.value, ValidationLevel.integration.value}
            ),
            regression_result=regression.to_dict(),
            review=task.review.to_dict(),
            acceptance=acceptance.to_dict(),
            repair_attempts=task.repair_attempts,
            risks=(task.risk.value, *task.review.risks),
            technical_debt=task.review.technical_debt,
            final_diff={
                "status_sha256": current.get("status_sha256"),
                "diff_sha256": current.get("diff_sha256"),
                "dirty": current.get("dirty"),
            },
            start_commit=_optional_mapping_text(baseline, "head"),
            end_commit=_optional_mapping_text(current, "head"),
            validation_report_id=validation.report_id,
            regression_report_id=regression.report_id,
        )
        self.store.write_record(
            f"reports/{task.id}/{report.report_id}.json",
            report.to_dict(),
        )
        return report

    def for_task(self, task_id: str) -> tuple[TaskReport, ...]:
        return tuple(
            TaskReport.from_dict(value) for value in self.store.list_records(f"reports/{task_id}")
        )

    def _latest_validation(self, task: ForgeTask) -> ValidationReport:
        reports = self.validations.current_for_task(task.id)
        if not reports or task.validation is None:
            raise ForgeConflictError("Task Report requires current validation evidence")
        report = next(
            (item for item in reversed(reports) if item.report_id == task.validation.report_id),
            None,
        )
        if report is None or not report.passed:
            raise ForgeConflictError("Task Report requires passing current validation")
        return report

    def _latest_regression(
        self,
        task: ForgeTask,
        validation: ValidationReport,
    ) -> RegressionReport:
        if task.validation is None or task.validation.regression_report_id is None:
            raise ForgeConflictError("Task Report requires linked L4 regression evidence")
        reports = self.regressions.for_task(task.id)
        report = next(
            (
                item
                for item in reversed(reports)
                if item.report_id == task.validation.regression_report_id
                and item.current_report_id == validation.report_id
            ),
            None,
        )
        if report is None or not report.passed:
            raise ForgeConflictError("Task Report requires passing L4 regression evidence")
        return report


def _command_projection(check: Any) -> dict[str, Any]:
    return {
        "check_id": check.check_id,
        "name": check.name,
        "level": check.level.value,
        "argv": list(check.argv),
        "status": check.status.value,
        "exit_code": check.exit_code,
        "duration_ms": check.duration_ms,
    }


def _text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a string")
    return item


def _optional_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{key} must be null or a string")
    return item


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or item < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return item


def _strings(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(items)


def _objects(value: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{key} must be an array of objects")
    return tuple(dict(item) for item in items)


def _object(value: dict[str, Any], key: str) -> dict[str, Any]:
    item = value.get(key)
    if not isinstance(item, dict):
        raise ValueError(f"{key} must be an object")
    return dict(item)


def _optional_mapping_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) else None
