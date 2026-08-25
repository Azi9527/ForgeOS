"""Versioned typed validation protocol shared by config, runners, and reports."""

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ValidationLevel(str, Enum):
    """ForgeOS V1 validation levels."""

    build = "L1_BUILD"
    unit = "L2_UNIT"
    integration = "L3_INTEGRATION"
    regression = "L4_REGRESSION"
    acceptance = "L5_ACCEPTANCE"


class ValidationStatus(str, Enum):
    """Typed outcome for one validation check or level."""

    passed = "PASS"
    failed = "FAIL"
    skipped = "SKIP"
    error = "ERROR"


class ValidationPurpose(str, Enum):
    """Whether commands describe the pre-change baseline or current workspace."""

    baseline = "BASELINE"
    current = "CURRENT"


@dataclass(frozen=True, slots=True)
class ValidationCheckResult:
    """Bounded evidence for one configured validation command."""

    check_id: str
    name: str
    level: ValidationLevel
    argv: tuple[str, ...]
    required: bool
    status: ValidationStatus
    exit_code: int | None
    timed_out: bool
    duration_ms: int
    stdout: str
    stderr: str
    error: str | None

    @property
    def passed(self) -> bool:
        return self.status is ValidationStatus.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "level": self.level.value,
            "argv": list(self.argv),
            "required": self.required,
            "status": self.status.value,
            "passed": self.passed,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ValidationCheckResult":
        argv = value.get("argv")
        if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
            raise ValueError("validation check argv must be an array of strings")
        required = value.get("required")
        if not isinstance(required, bool):
            raise ValueError("validation check required must be a boolean")
        status_value = value.get("status")
        if status_value is None:
            status_value = "PASS" if value.get("passed") is True else "FAIL"
        return cls(
            check_id=_required_string(
                value,
                "check_id",
                default=check_identity(
                    str(value.get("name", "legacy")),
                    ValidationLevel(value.get("level", ValidationLevel.unit.value)),
                    tuple(argv),
                ),
            ),
            name=_required_string(value, "name"),
            level=ValidationLevel(value.get("level", ValidationLevel.unit.value)),
            argv=tuple(argv),
            required=required,
            status=ValidationStatus(status_value),
            exit_code=_optional_int(value, "exit_code"),
            timed_out=_required_bool(value, "timed_out"),
            duration_ms=_required_non_negative_int(value, "duration_ms"),
            stdout=_required_string(value, "stdout", allow_empty=True),
            stderr=_required_string(value, "stderr", allow_empty=True),
            error=_optional_string(value, "error"),
        )


@dataclass(frozen=True, slots=True)
class ValidationLevelResult:
    """Aggregate typed result for one level represented in a report."""

    level: ValidationLevel
    status: ValidationStatus
    required: bool
    check_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "status": self.status.value,
            "required": self.required,
            "check_ids": list(self.check_ids),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ValidationLevelResult":
        check_ids = value.get("check_ids")
        if not isinstance(check_ids, list) or not all(isinstance(item, str) for item in check_ids):
            raise ValueError("validation level check_ids must be an array of strings")
        return cls(
            level=ValidationLevel(_required_string(value, "level")),
            status=ValidationStatus(_required_string(value, "status")),
            required=_required_bool(value, "required"),
            check_ids=tuple(check_ids),
        )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Independent aggregate validation evidence with typed level summaries."""

    report_id: str
    task_id: str
    purpose: ValidationPurpose
    passed: bool
    started_at: str
    completed_at: str
    checks: tuple[ValidationCheckResult, ...]
    levels: tuple[ValidationLevelResult, ...]
    schema_version: int = 2

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "task_id": self.task_id,
            "purpose": self.purpose.value,
            "passed": self.passed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "checks": [check.to_dict() for check in self.checks],
            "levels": [level.to_dict() for level in self.levels],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ValidationReport":
        version = value.get("schema_version")
        if version not in {1, 2}:
            raise ValueError(f"unsupported validation report schema: {version!r}")
        checks_value = value.get("checks")
        if not isinstance(checks_value, list) or not all(
            isinstance(item, dict) for item in checks_value
        ):
            raise ValueError("validation checks must be an array of objects")
        checks = tuple(ValidationCheckResult.from_dict(item) for item in checks_value)
        levels_value = value.get("levels")
        levels = (
            tuple(ValidationLevelResult.from_dict(item) for item in levels_value)
            if isinstance(levels_value, list)
            and all(isinstance(item, dict) for item in levels_value)
            else summarize_levels(checks)
        )
        return cls(
            report_id=_required_string(value, "report_id"),
            task_id=_required_string(value, "task_id"),
            purpose=ValidationPurpose(value.get("purpose", ValidationPurpose.current.value)),
            passed=_required_bool(value, "passed"),
            started_at=_required_string(value, "started_at"),
            completed_at=_required_string(value, "completed_at"),
            checks=checks,
            levels=levels,
        )


def check_identity(name: str, level: ValidationLevel, argv: tuple[str, ...]) -> str:
    """Return a stable identifier for baseline/current check matching."""

    payload = "\0".join((level.value, name, *argv)).encode("utf-8")
    return f"check-{hashlib.sha256(payload).hexdigest()[:24]}"


def summarize_levels(
    checks: tuple[ValidationCheckResult, ...],
) -> tuple[ValidationLevelResult, ...]:
    summaries: list[ValidationLevelResult] = []
    for level in ValidationLevel:
        selected = tuple(check for check in checks if check.level is level)
        if not selected:
            continue
        required = any(check.required for check in selected)
        statuses = {check.status for check in selected if check.required} or {
            check.status for check in selected
        }
        if ValidationStatus.error in statuses:
            status = ValidationStatus.error
        elif ValidationStatus.failed in statuses:
            status = ValidationStatus.failed
        elif statuses == {ValidationStatus.skipped}:
            status = ValidationStatus.skipped
        else:
            status = ValidationStatus.passed
        summaries.append(
            ValidationLevelResult(
                level=level,
                status=status,
                required=required,
                check_ids=tuple(check.check_id for check in selected),
            )
        )
    return tuple(summaries)


def _required_string(
    value: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
    default: str | None = None,
) -> str:
    item = value.get(key, default)
    if not isinstance(item, str) or (not allow_empty and not item.strip()):
        raise ValueError(f"{key} must be a string")
    return item


def _required_bool(value: dict[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"{key} must be a boolean")
    return item


def _required_non_negative_int(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or item < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return item


def _optional_int(value: dict[str, Any], key: str) -> int | None:
    item = value.get(key)
    if item is not None and not isinstance(item, int):
        raise ValueError(f"{key} must be null or an integer")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is not None and not isinstance(item, str):
        raise ValueError(f"{key} must be null or a string")
    return item
