"""Baseline-aware regression classification and persistent validation repositories."""

from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from .errors import ForgeConflictError
from .storage import ForgeStore
from .validation_types import ValidationCheckResult, ValidationPurpose, ValidationReport


class RegressionClassification(str, Enum):
    """Relationship between the same check before and after task execution."""

    unchanged_pass = "UNCHANGED_PASS"
    fixed = "FIXED"
    pre_existing_failure = "PRE_EXISTING_FAILURE"
    new_regression = "NEW_REGRESSION"
    missing_current = "MISSING_CURRENT"
    new_check_pass = "NEW_CHECK_PASS"


@dataclass(frozen=True, slots=True)
class RegressionCheckResult:
    """One baseline/current check comparison."""

    check_id: str
    name: str
    level: str
    required: bool
    classification: RegressionClassification
    baseline_status: str
    current_status: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "level": self.level,
            "required": self.required,
            "classification": self.classification.value,
            "baseline_status": self.baseline_status,
            "current_status": self.current_status,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RegressionCheckResult":
        required = value.get("required")
        if not isinstance(required, bool):
            raise ValueError("regression required must be a boolean")
        current = value.get("current_status")
        if current is not None and not isinstance(current, str):
            raise ValueError("current_status must be null or a string")
        return cls(
            check_id=_required_string(value, "check_id"),
            name=_required_string(value, "name"),
            level=_required_string(value, "level"),
            required=required,
            classification=RegressionClassification(_required_string(value, "classification")),
            baseline_status=_required_string(value, "baseline_status"),
            current_status=current,
        )


@dataclass(frozen=True, slots=True)
class RegressionReport:
    """Independent L4 evidence distinguishing existing failures from regressions."""

    report_id: str
    task_id: str
    baseline_report_id: str
    current_report_id: str
    passed: bool
    completed_at: str
    checks: tuple[RegressionCheckResult, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "task_id": self.task_id,
            "baseline_report_id": self.baseline_report_id,
            "current_report_id": self.current_report_id,
            "passed": self.passed,
            "completed_at": self.completed_at,
            "checks": [check.to_dict() for check in self.checks],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RegressionReport":
        if value.get("schema_version") != 1:
            raise ValueError(f"unsupported regression schema: {value.get('schema_version')!r}")
        checks = value.get("checks")
        if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
            raise ValueError("regression checks must be an array of objects")
        passed = value.get("passed")
        if not isinstance(passed, bool):
            raise ValueError("regression passed must be a boolean")
        return cls(
            report_id=_required_string(value, "report_id"),
            task_id=_required_string(value, "task_id"),
            baseline_report_id=_required_string(value, "baseline_report_id"),
            current_report_id=_required_string(value, "current_report_id"),
            passed=passed,
            completed_at=_required_string(value, "completed_at"),
            checks=tuple(RegressionCheckResult.from_dict(item) for item in checks),
        )


class ValidationReportRepository:
    """Persist immutable baseline reports and append-only current reports."""

    def __init__(self, store: ForgeStore) -> None:
        self.store = store

    def save(self, report: ValidationReport) -> ValidationReport:
        if report.purpose is ValidationPurpose.baseline:
            path = self.store.forge_dir / "validation" / "baselines" / f"{report.task_id}.json"
            if path.exists():
                existing = ValidationReport.from_dict(self.store.read_json(path))
                if existing != report:
                    raise ForgeConflictError(
                        f"validation baseline already exists for {report.task_id}"
                    )
                return existing
            self.store.write_record(
                f"validation/baselines/{report.task_id}.json",
                report.to_dict(),
            )
        else:
            self.store.write_record(
                f"validation/results/{report.report_id}.json",
                report.to_dict(),
            )
        return report

    def baseline(self, task_id: str) -> ValidationReport | None:
        path = self.store.forge_dir / "validation" / "baselines" / f"{task_id}.json"
        return ValidationReport.from_dict(self.store.read_json(path)) if path.is_file() else None

    def current_for_task(self, task_id: str) -> tuple[ValidationReport, ...]:
        reports = (
            ValidationReport.from_dict(value)
            for value in self.store.list_records("validation/results")
            if value.get("task_id") == task_id
        )
        return tuple(report for report in reports if report.purpose is ValidationPurpose.current)


class RegressionService:
    """Compare current checks with an immutable pre-execution baseline."""

    def __init__(self, store: ForgeStore, *, clock: Any) -> None:
        self.store = store
        self.clock = clock

    def compare(
        self,
        baseline: ValidationReport,
        current: ValidationReport,
    ) -> RegressionReport:
        if baseline.task_id != current.task_id:
            raise ValueError("baseline and current reports belong to different tasks")
        if baseline.purpose is not ValidationPurpose.baseline:
            raise ValueError("baseline report has the wrong purpose")
        if current.purpose is not ValidationPurpose.current:
            raise ValueError("current report has the wrong purpose")
        current_by_id = {check.check_id: check for check in current.checks}
        results = tuple(
            _compare_check(check, current_by_id.get(check.check_id)) for check in baseline.checks
        )
        baseline_ids = {check.check_id for check in baseline.checks}
        results += tuple(
            _new_check_result(check)
            for check in current.checks
            if check.check_id not in baseline_ids
        )
        passed = not any(
            result.required
            and result.classification
            in {RegressionClassification.new_regression, RegressionClassification.missing_current}
            for result in results
        )
        report = RegressionReport(
            report_id=f"regression-{uuid4()}",
            task_id=current.task_id,
            baseline_report_id=baseline.report_id,
            current_report_id=current.report_id,
            passed=passed,
            completed_at=self.clock(),
            checks=results,
        )
        self.store.write_record(
            f"validation/regression/{report.report_id}.json",
            report.to_dict(),
        )
        return report

    def for_task(self, task_id: str) -> tuple[RegressionReport, ...]:
        return tuple(
            RegressionReport.from_dict(value)
            for value in self.store.list_records("validation/regression")
            if value.get("task_id") == task_id
        )


def _compare_check(
    baseline: ValidationCheckResult,
    current: ValidationCheckResult | None,
) -> RegressionCheckResult:
    if current is None:
        classification = RegressionClassification.missing_current
    elif baseline.passed and current.passed:
        classification = RegressionClassification.unchanged_pass
    elif not baseline.passed and current.passed:
        classification = RegressionClassification.fixed
    elif baseline.passed and not current.passed:
        classification = RegressionClassification.new_regression
    else:
        classification = RegressionClassification.pre_existing_failure
    return RegressionCheckResult(
        check_id=baseline.check_id,
        name=baseline.name,
        level=baseline.level.value,
        required=baseline.required,
        classification=classification,
        baseline_status=baseline.status.value,
        current_status=current.status.value if current else None,
    )


def _new_check_result(current: ValidationCheckResult) -> RegressionCheckResult:
    return RegressionCheckResult(
        check_id=current.check_id,
        name=current.name,
        level=current.level.value,
        required=current.required,
        classification=(
            RegressionClassification.new_check_pass
            if current.passed
            else RegressionClassification.new_regression
        ),
        baseline_status="NOT_PRESENT",
        current_status=current.status.value,
    )


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return item
