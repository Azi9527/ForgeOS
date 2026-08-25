"""Bounded, cursor-based queries over the append-only Forge audit log."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .audit import AuditActor, AuditEvent, AuditLog

MAX_AUDIT_PAGE = 200


@dataclass(frozen=True, slots=True)
class AuditPage:
    """One stable ascending page of filtered audit events."""

    events: tuple[AuditEvent, ...]
    next_cursor: int | None
    matched: int
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "events": [event.to_dict() for event in self.events],
            "next_cursor": self.next_cursor,
            "matched": self.matched,
        }


class AuditQueryService:
    """Filter audit evidence without mutating or rewriting the source log."""

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def query(
        self,
        *,
        task_id: str | None = None,
        event_type: str | None = None,
        actor: AuditActor | None = None,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> AuditPage:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= MAX_AUDIT_PAGE:
            raise ValueError(f"limit must be between 1 and {MAX_AUDIT_PAGE}")
        normalized_task = task_id.strip() if task_id else None
        normalized_type = event_type.strip() if event_type else None
        matched = tuple(
            event
            for event in self.audit.read_all()
            if event.sequence > after_sequence
            and (normalized_task is None or event.task_id == normalized_task)
            and (normalized_type is None or event.event_type == normalized_type)
            and (actor is None or event.actor is actor)
        )
        page = matched[:limit]
        next_cursor = page[-1].sequence if len(matched) > limit else None
        return AuditPage(events=page, next_cursor=next_cursor, matched=len(matched))

    def event_types(self) -> tuple[str, ...]:
        return tuple(sorted({event.event_type for event in self.audit.read_all()}))
