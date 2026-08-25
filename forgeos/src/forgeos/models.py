"""Versioned ForgeOS domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from .governance import AcceptanceEvidence, ReviewEvidence

SCHEMA_VERSION = 1


class TaskType(str, Enum):
    """Supported ForgeTask categories."""

    feature = "FEATURE"
    fix = "FIX"
    refactor = "REFACTOR"
    review = "REVIEW"
    documentation = "DOC"
    test = "TEST"


class TaskStatus(str, Enum):
    """Authoritative ForgeTask lifecycle states."""

    created = "CREATED"
    analyzing = "ANALYZING"
    planned = "PLANNED"
    implementing = "IMPLEMENTING"
    validating = "VALIDATING"
    repairing = "REPAIRING"
    reviewing = "REVIEWING"
    accepting = "ACCEPTING"
    done = "DONE"
    blocked = "BLOCKED"
    failed = "FAILED"
    cancelled = "CANCELLED"


class TaskPriority(str, Enum):
    """Scheduling priority without hidden numeric meaning."""

    low = "LOW"
    normal = "NORMAL"
    high = "HIGH"
    critical = "CRITICAL"


class TaskRisk(str, Enum):
    """Engineering risk used by policy and review."""

    low = "LOW"
    medium = "MEDIUM"
    high = "HIGH"


@dataclass(frozen=True, slots=True)
class ForgeProject:
    """Stable identity for one ForgeOS-governed workspace."""

    id: str
    name: str
    root: str
    created_at: str
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(cls, *, name: str, root: Path, created_at: str) -> ForgeProject:
        canonical_root = root.resolve()
        if not canonical_root.is_dir():
            raise ValueError(f"project root must be an existing directory: {canonical_root}")
        return cls(
            id=f"project-{uuid4()}",
            name=_bounded_text(name, field_name="project name", maximum=120),
            root=str(canonical_root),
            created_at=created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "root": self.root,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ForgeProject:
        _require_schema(value)
        return cls(
            id=_required_string(value, "id"),
            name=_required_string(value, "name"),
            root=_required_string(value, "root"),
            created_at=_required_string(value, "created_at"),
        )


@dataclass(frozen=True, slots=True)
class ValidationEvidence:
    """Persisted evidence from one independent validation run."""

    report_id: str
    passed: bool
    checked_at: str
    regression_report_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "passed": self.passed,
            "checked_at": self.checked_at,
            "regression_report_id": self.regression_report_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ValidationEvidence:
        passed = value.get("passed")
        if not isinstance(passed, bool):
            raise ValueError("validation evidence passed must be a boolean")
        return cls(
            report_id=_required_string(value, "report_id"),
            passed=passed,
            checked_at=_required_string(value, "checked_at"),
            regression_report_id=_optional_string(value, "regression_report_id"),
        )


@dataclass(frozen=True, slots=True)
class ForgeTask:
    """Versioned engineering task whose status is owned only by ForgeOS."""

    id: str
    title: str
    task_type: TaskType
    objective: str
    acceptance_criteria: tuple[str, ...]
    status: TaskStatus
    priority: TaskPriority
    risk: TaskRisk
    created_at: str
    updated_at: str
    revision: int = 0
    repair_attempts: int = 0
    constraints: tuple[str, ...] = ()
    related_modules: tuple[str, ...] = ()
    blocked_from: TaskStatus | None = None
    codex_thread_id: str | None = None
    last_turn_id: str | None = None
    validation: ValidationEvidence | None = None
    review: ReviewEvidence | None = None
    acceptance: AcceptanceEvidence | None = None
    task_report_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        title: str,
        task_type: TaskType,
        objective: str,
        acceptance_criteria: tuple[str, ...],
        created_at: str,
        priority: TaskPriority = TaskPriority.normal,
        risk: TaskRisk = TaskRisk.medium,
        constraints: tuple[str, ...] = (),
        related_modules: tuple[str, ...] = (),
    ) -> ForgeTask:
        if not acceptance_criteria:
            raise ValueError("acceptance_criteria must contain at least one item")
        return cls(
            id=_bounded_text(task_id, field_name="task id", maximum=64),
            title=_bounded_text(title, field_name="title", maximum=200),
            task_type=task_type,
            objective=_bounded_text(objective, field_name="objective", maximum=10_000),
            acceptance_criteria=_bounded_items(
                acceptance_criteria,
                field_name="acceptance criteria",
                item_maximum=2_000,
                count_maximum=100,
            ),
            status=TaskStatus.created,
            priority=priority,
            risk=risk,
            created_at=created_at,
            updated_at=created_at,
            constraints=_bounded_items(
                constraints,
                field_name="constraints",
                item_maximum=2_000,
                count_maximum=100,
            ),
            related_modules=_bounded_items(
                related_modules,
                field_name="related modules",
                item_maximum=500,
                count_maximum=200,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "title": self.title,
            "task_type": self.task_type.value,
            "objective": self.objective,
            "acceptance_criteria": list(self.acceptance_criteria),
            "status": self.status.value,
            "priority": self.priority.value,
            "risk": self.risk.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "revision": self.revision,
            "repair_attempts": self.repair_attempts,
            "constraints": list(self.constraints),
            "related_modules": list(self.related_modules),
            "blocked_from": self.blocked_from.value if self.blocked_from else None,
            "codex_thread_id": self.codex_thread_id,
            "last_turn_id": self.last_turn_id,
            "validation": self.validation.to_dict() if self.validation else None,
            "review": self.review.to_dict() if self.review else None,
            "acceptance": self.acceptance.to_dict() if self.acceptance else None,
            "task_report_id": self.task_report_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ForgeTask:
        _require_schema(value)
        revision = value.get("revision")
        if not isinstance(revision, int) or revision < 0:
            raise ValueError("task revision must be a non-negative integer")
        repair_attempts = value.get("repair_attempts", 0)
        if not isinstance(repair_attempts, int) or repair_attempts < 0:
            raise ValueError("task repair_attempts must be a non-negative integer")
        blocked_from = value.get("blocked_from")
        return cls(
            id=_required_string(value, "id"),
            title=_required_string(value, "title"),
            task_type=TaskType(_required_string(value, "task_type")),
            objective=_required_string(value, "objective"),
            acceptance_criteria=_string_tuple(value, "acceptance_criteria"),
            status=TaskStatus(_required_string(value, "status")),
            priority=TaskPriority(_required_string(value, "priority")),
            risk=TaskRisk(_required_string(value, "risk")),
            created_at=_required_string(value, "created_at"),
            updated_at=_required_string(value, "updated_at"),
            revision=revision,
            repair_attempts=repair_attempts,
            constraints=_string_tuple(value, "constraints"),
            related_modules=_string_tuple(value, "related_modules"),
            blocked_from=TaskStatus(blocked_from) if blocked_from is not None else None,
            codex_thread_id=_optional_string(value, "codex_thread_id"),
            last_turn_id=_optional_string(value, "last_turn_id"),
            validation=_optional_object(value, "validation", ValidationEvidence.from_dict),
            review=_optional_object(value, "review", ReviewEvidence.from_dict),
            acceptance=_optional_object(value, "acceptance", AcceptanceEvidence.from_dict),
            task_report_id=_optional_string(value, "task_report_id"),
        )


def _require_schema(value: dict[str, Any]) -> None:
    version = value.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {version!r}")


def _bounded_text(value: str, *, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")
    return normalized


def _bounded_items(
    values: tuple[str, ...],
    *,
    field_name: str,
    item_maximum: int,
    count_maximum: int,
) -> tuple[str, ...]:
    if len(values) > count_maximum:
        raise ValueError(f"{field_name} exceeds {count_maximum} items")
    return tuple(
        _bounded_text(value, field_name=field_name, maximum=item_maximum) for value in values
    )


def _required_string(
    value: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    item = value.get(key)
    if not isinstance(item, str) or (not allow_empty and not item.strip()):
        raise ValueError(f"{key} must be a string")
    return item


def _optional_string(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{key} must be null or a non-empty string")
    return item


def _string_tuple(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(items)


def _optional_object(
    value: dict[str, Any],
    key: str,
    loader: Any,
) -> Any:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, dict):
        raise ValueError(f"{key} must be null or an object")
    return loader(item)
