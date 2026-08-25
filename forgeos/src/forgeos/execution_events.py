"""Bounded progress and active-turn control at the Codex SDK boundary."""

import threading
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CodexProgressEvent:
    """Allowlisted progress summary that is safe to persist or display."""

    sequence: int
    method: str
    summary: dict[str, Any]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "method": self.method,
            "summary": self.summary,
        }


class SdkTurnHandle(Protocol):
    """Public SDK TurnHandle behavior used by ForgeOS controlled execution."""

    id: str

    def stream(self) -> Any: ...

    def interrupt(self) -> Any: ...

    def steer(self, input: str) -> Any: ...


class CodexTurnControl:
    """Thread-safe narrow control surface for one active SDK TurnHandle."""

    def __init__(self, *, thread_id: str, handle: SdkTurnHandle) -> None:
        self.thread_id = thread_id
        self.turn_id = str(handle.id)
        self._handle = handle
        self._lock = threading.Lock()
        self._interrupt_requested = False

    @property
    def interrupt_requested(self) -> bool:
        with self._lock:
            return self._interrupt_requested

    def interrupt(self) -> dict[str, Any]:
        with self._lock:
            if self._interrupt_requested:
                return {"already_requested": True}
            self._interrupt_requested = True
        return _public_result(self._handle.interrupt())

    def steer(self, input: str) -> dict[str, Any]:
        normalized = input.strip()
        if not normalized:
            raise ValueError("steer input must not be empty")
        if len(normalized.encode("utf-8")) > 10_000:
            raise ValueError("steer input exceeds 10000 bytes")
        with self._lock:
            if self._interrupt_requested:
                raise ValueError("cannot steer after interrupt was requested")
        return _public_result(self._handle.steer(normalized))


def _public_result(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "model_dump"):
        result = value.model_dump(mode="json", by_alias=True)
        return result if isinstance(result, dict) else {"result": result}
    if isinstance(value, dict):
        return dict(value)
    return {"result_type": type(value).__name__}
