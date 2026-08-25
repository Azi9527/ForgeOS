"""Append-only, redacted ForgeOS audit events."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any
from uuid import uuid4

from .errors import ForgeConfigError
from .storage import ForgeStore


class AuditActor(str, Enum):
    """Authorities allowed to write ForgeOS state transitions."""

    human = "human"
    system = "system"
    validation = "validation"
    reviewer = "reviewer"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One versioned append-only engineering event."""

    sequence: int
    event_id: str
    event_type: str
    occurred_at: str
    actor: AuditActor
    task_id: str | None
    payload: dict[str, Any]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "actor": self.actor.value,
            "task_id": self.task_id,
            "payload": self.payload,
        }


class AuditLog:
    """Serialize and append bounded audit events under the Forge store lock."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock

    def append(
        self,
        event_type: str,
        *,
        actor: AuditActor,
        task_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        if not event_type.strip():
            raise ValueError("event_type must not be empty")
        redacted = _redact(payload or {})
        lock_path = self.store.forge_dir / "logs" / ".audit.lock"
        with self.store.exclusive_lock(lock_path):
            sequence_path = self.store.forge_dir / "logs" / "sequence.json"
            sequence = 1
            if sequence_path.exists():
                value = self.store.read_json(sequence_path)
                last = value.get("last")
                if not isinstance(last, int) or last < 0:
                    raise ForgeConfigError("audit sequence is invalid")
                sequence = last + 1

            event = AuditEvent(
                sequence=sequence,
                event_id=f"audit-{uuid4()}",
                event_type=event_type,
                occurred_at=self.clock(),
                actor=actor,
                task_id=task_id,
                payload=redacted,
            )
            line = json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
            if len(line.encode("utf-8")) > 65_536:
                raise ForgeConfigError("audit event exceeds 65536 bytes")

            self.store.write_json(sequence_path, {"schema_version": 1, "last": sequence})
            audit_path = self.store.forge_dir / "logs" / "audit.jsonl"
            with audit_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        return event

    def read_all(self) -> tuple[AuditEvent, ...]:
        path = self.store.forge_dir / "logs" / "audit.jsonl"
        if not path.exists():
            return ()
        events: list[AuditEvent] = []
        expected_sequence = 1
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ForgeConfigError(f"invalid audit line {line_number}: {exc}") from exc
            if value.get("sequence") != expected_sequence:
                raise ForgeConfigError(
                    f"audit sequence gap at line {line_number}: expected {expected_sequence}"
                )
            events.append(
                AuditEvent(
                    sequence=expected_sequence,
                    event_id=value["event_id"],
                    event_type=value["event_type"],
                    occurred_at=value["occurred_at"],
                    actor=AuditActor(value["actor"]),
                    task_id=value.get("task_id"),
                    payload=value.get("payload", {}),
                    schema_version=value.get("schema_version", 1),
                )
            )
            expected_sequence += 1
        return tuple(events)


_SECRET_PARTS = ("authorization", "password", "secret", "token", "api_key", "apikey")


def _redact(value: Any, *, key: str = "") -> Any:
    normalized_key = key.lower().replace("-", "_")
    if any(part in normalized_key for part in _SECRET_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item, key=str(item_key)) for item_key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)
