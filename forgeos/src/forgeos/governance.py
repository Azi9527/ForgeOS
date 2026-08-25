"""Structured human Review and Acceptance evidence for Forge task authority gates."""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .errors import ForgeConflictError


class ReviewDimension(str, Enum):
    """Required V1 engineering review dimensions."""

    architecture = "ARCHITECTURE"
    code_quality = "CODE_QUALITY"
    risk = "RISK"
    tests = "TESTS"
    backward_compatibility = "BACKWARD_COMPATIBILITY"
    technical_debt = "TECHNICAL_DEBT"


class ReviewStatus(str, Enum):
    """One review dimension decision."""

    passed = "PASS"
    concern = "CONCERN"
    not_applicable = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class ReviewChecklistItem:
    """Traceable result for one required review dimension."""

    dimension: ReviewDimension
    status: ReviewStatus
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension.value,
            "status": self.status.value,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReviewChecklistItem":
        return cls(
            dimension=ReviewDimension(_required_string(value, "dimension")),
            status=ReviewStatus(_required_string(value, "status")),
            note=_required_string(value, "note", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    """Persisted structured review decision independent of the coding agent."""

    approved: bool
    reviewer: str
    reviewed_at: str
    summary: str
    checklist: tuple[ReviewChecklistItem, ...] = ()
    risks: tuple[str, ...] = ()
    technical_debt: tuple[str, ...] = ()

    @property
    def checklist_complete(self) -> bool:
        dimensions = tuple(item.dimension for item in self.checklist)
        return len(dimensions) == len(ReviewDimension) and set(dimensions) == set(ReviewDimension)

    @property
    def passed(self) -> bool:
        return (
            self.approved
            and self.checklist_complete
            and all(item.status is not ReviewStatus.concern for item in self.checklist)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "summary": self.summary,
            "checklist": [item.to_dict() for item in self.checklist],
            "risks": list(self.risks),
            "technical_debt": list(self.technical_debt),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ReviewEvidence":
        approved = value.get("approved")
        if not isinstance(approved, bool):
            raise ValueError("review evidence approved must be a boolean")
        checklist = _object_list(value, "checklist", default=())
        return cls(
            approved=approved,
            reviewer=_required_string(value, "reviewer"),
            reviewed_at=_required_string(value, "reviewed_at"),
            summary=_required_string(value, "summary", allow_empty=True),
            checklist=tuple(ReviewChecklistItem.from_dict(item) for item in checklist),
            risks=_string_tuple(value, "risks", default=()),
            technical_debt=_string_tuple(value, "technical_debt", default=()),
        )


class CriterionStatus(str, Enum):
    """Human acceptance result for one declared criterion."""

    passed = "PASS"
    failed = "FAIL"
    skipped = "SKIP"


@dataclass(frozen=True, slots=True)
class AcceptanceCriterionEvidence:
    """Evidence-backed result for exactly one task acceptance criterion."""

    criterion_id: str
    criterion: str
    status: CriterionStatus
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "criterion": self.criterion,
            "status": self.status.value,
            "evidence": self.evidence,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcceptanceCriterionEvidence":
        return cls(
            criterion_id=_required_string(value, "criterion_id"),
            criterion=_required_string(value, "criterion"),
            status=CriterionStatus(_required_string(value, "status")),
            evidence=_required_string(value, "evidence", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """Final non-agent authority decision with criterion-level evidence."""

    accepted_by: str
    accepted_at: str
    note: str
    criteria: tuple[AcceptanceCriterionEvidence, ...] = ()

    @property
    def passed(self) -> bool:
        return bool(self.criteria) and all(
            item.status is CriterionStatus.passed and item.evidence.strip()
            for item in self.criteria
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted_by": self.accepted_by,
            "accepted_at": self.accepted_at,
            "note": self.note,
            "criteria": [item.to_dict() for item in self.criteria],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcceptanceEvidence":
        criteria = _object_list(value, "criteria", default=())
        return cls(
            accepted_by=_required_string(value, "accepted_by"),
            accepted_at=_required_string(value, "accepted_at"),
            note=_required_string(value, "note", allow_empty=True),
            criteria=tuple(AcceptanceCriterionEvidence.from_dict(item) for item in criteria),
        )


def validate_review_evidence(evidence: ReviewEvidence) -> None:
    """Fail closed unless every review dimension has one coherent result."""

    if not evidence.checklist_complete:
        raise ForgeConflictError(
            "review checklist must cover every required dimension exactly once"
        )
    if evidence.approved and not evidence.passed:
        raise ForgeConflictError("approved review cannot contain unresolved concerns")
    for item in evidence.checklist:
        if item.status is ReviewStatus.not_applicable and not item.note.strip():
            raise ForgeConflictError("NOT_APPLICABLE review items require an explanation")


def validate_human_authority(authority: str, action: str) -> None:
    """Reject model identities at every human Review/Acceptance boundary."""

    normalized = authority.strip().lower()
    if not normalized:
        raise ForgeConflictError(f"human authority is required for Forge {action}")
    if any(
        part in normalized
        for part in (
            "agent",
            "codex",
            "model",
            "assistant",
            "system",
            "forgeos",
            "automation",
            "validation",
        )
    ):
        raise ForgeConflictError(
            f"coding agents and non-human identities cannot authorize Forge {action}"
        )


def validate_acceptance_evidence(
    declared_criteria: tuple[str, ...],
    evidence: AcceptanceEvidence,
) -> None:
    """Require one passing, non-empty evidence item for every declared criterion."""

    expected = tuple(
        (f"AC-{index:03d}", criterion) for index, criterion in enumerate(declared_criteria, 1)
    )
    actual = tuple((item.criterion_id, item.criterion) for item in evidence.criteria)
    if actual != expected:
        raise ForgeConflictError("acceptance evidence must match every declared criterion in order")
    if not evidence.passed:
        raise ForgeConflictError("all acceptance criteria require PASS with non-empty evidence")


def _required_string(
    value: dict[str, Any],
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    item = value.get(key)
    if not isinstance(item, str) or (not allow_empty and not item.strip()):
        raise ValueError(f"{key} must be a string")
    if len(item) > 10_000:
        raise ValueError(f"{key} exceeds 10000 characters")
    return item


def _string_tuple(
    value: dict[str, Any],
    key: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    items = value.get(key, list(default))
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    if len(items) > 100:
        raise ValueError(f"{key} exceeds 100 items")
    return tuple(items)


def _object_list(
    value: dict[str, Any],
    key: str,
    *,
    default: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    items = value.get(key, list(default))
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise ValueError(f"{key} must be an array of objects")
    return tuple(items)
