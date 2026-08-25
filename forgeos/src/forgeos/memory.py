"""Accepted, bounded, file-backed engineering memory and deterministic retrieval."""

import hashlib
import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from ._memory_codec import bounded as _bounded
from ._memory_codec import bounded_items as _bounded_items
from ._memory_codec import content_hash as _content_hash
from ._memory_codec import is_non_human as _is_non_human
from ._memory_codec import non_negative as _non_negative
from ._memory_codec import optional_text as _optional_text
from ._memory_codec import require_human as _require_human
from ._memory_codec import strings as _strings
from ._memory_codec import text as _text
from .audit import AuditActor, AuditLog
from .errors import ForgeConflictError, ForgeNotFoundError
from .models import ForgeTask
from .storage import ForgeStore

SCHEMA_VERSION = 1
BODY_LIMIT = 8_192
SELECTION_LIMIT = 16_384
SELECTION_COUNT = 8


class MemoryKind(str, Enum):
    """Engineering knowledge categories owned by ForgeOS."""

    decision = "DECISION"
    failure = "FAILURE"
    pattern = "PATTERN"
    task = "TASK"


class MemoryStatus(str, Enum):
    """Human-governed lifecycle of a memory record."""

    draft = "DRAFT"
    accepted = "ACCEPTED"
    rejected = "REJECTED"
    superseded = "SUPERSEDED"


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """One bounded memory artifact; only ACCEPTED records may enter context."""

    id: str
    kind: MemoryKind
    status: MemoryStatus
    title: str
    body: str
    tags: tuple[str, ...]
    related_modules: tuple[str, ...]
    created_at: str
    created_by: str
    revision: int
    content_sha256: str
    source_task_id: str | None = None
    source_report_id: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    superseded_by: str | None = None
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def create(
        cls,
        *,
        kind: MemoryKind,
        title: str,
        body: str,
        tags: tuple[str, ...],
        related_modules: tuple[str, ...],
        created_at: str,
        created_by: str,
        source_task_id: str | None = None,
        source_report_id: str | None = None,
    ) -> "MemoryRecord":
        title = _bounded(title, "title", 200)
        body = _bounded(body, "body", BODY_LIMIT)
        tags = _bounded_items(tags, "tags", 50, 100)
        modules = _bounded_items(related_modules, "related_modules", 100, 500)
        creator = _bounded(created_by, "created_by", 120)
        digest = _content_hash(kind.value, title, body, tags, modules)
        return cls(
            id=f"memory-{uuid4()}",
            kind=kind,
            status=MemoryStatus.draft,
            title=title,
            body=body,
            tags=tags,
            related_modules=modules,
            created_at=created_at,
            created_by=creator,
            revision=0,
            content_sha256=digest,
            source_task_id=source_task_id,
            source_report_id=source_report_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "kind": self.kind.value,
            "status": self.status.value,
            "title": self.title,
            "body": self.body,
            "tags": list(self.tags),
            "related_modules": list(self.related_modules),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "revision": self.revision,
            "content_sha256": self.content_sha256,
            "source_task_id": self.source_task_id,
            "source_report_id": self.source_report_id,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision_reason": self.decision_reason,
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MemoryRecord":
        if value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported MemoryRecord schema_version")
        record = cls(
            id=_text(value, "id"),
            kind=MemoryKind(_text(value, "kind")),
            status=MemoryStatus(_text(value, "status")),
            title=_text(value, "title"),
            body=_text(value, "body"),
            tags=_strings(value, "tags"),
            related_modules=_strings(value, "related_modules"),
            created_at=_text(value, "created_at"),
            created_by=_text(value, "created_by"),
            revision=_non_negative(value, "revision"),
            content_sha256=_text(value, "content_sha256"),
            source_task_id=_optional_text(value, "source_task_id"),
            source_report_id=_optional_text(value, "source_report_id"),
            decided_at=_optional_text(value, "decided_at"),
            decided_by=_optional_text(value, "decided_by"),
            decision_reason=_optional_text(value, "decision_reason"),
            superseded_by=_optional_text(value, "superseded_by"),
        )
        expected = _content_hash(
            record.kind.value, record.title, record.body, record.tags, record.related_modules
        )
        if record.content_sha256 != expected:
            raise ValueError(f"memory content hash mismatch: {record.id}")
        return record


@dataclass(frozen=True, slots=True)
class MemorySelectionItem:
    memory_id: str
    score: int
    reasons: tuple[str, ...]
    content_sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "score": self.score,
            "reasons": list(self.reasons),
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class MemorySelection:
    id: str
    task_id: str
    created_at: str
    query_sha256: str
    items: tuple[MemorySelectionItem, ...]
    total_bytes: int
    truncated: bool
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "query_sha256": self.query_sha256,
            "items": [item.to_dict() for item in self.items],
            "total_bytes": self.total_bytes,
            "truncated": self.truncated,
        }


class MemoryService:
    """Own memory persistence, human decisions, retrieval evidence, and audit."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def create(
        self,
        *,
        kind: MemoryKind,
        title: str,
        body: str,
        created_by: str,
        tags: tuple[str, ...] = (),
        related_modules: tuple[str, ...] = (),
        source_task_id: str | None = None,
        source_report_id: str | None = None,
    ) -> MemoryRecord:
        record = MemoryRecord.create(
            kind=kind,
            title=title,
            body=body,
            tags=tags,
            related_modules=related_modules,
            created_at=self.clock(),
            created_by=created_by,
            source_task_id=source_task_id,
            source_report_id=source_report_id,
        )
        self.store.write_record(_record_path(record), record.to_dict())
        self.audit.append(
            "memory.created",
            actor=AuditActor.system if _is_non_human(created_by) else AuditActor.human,
            task_id=source_task_id,
            payload={"memory_id": record.id, "kind": record.kind.value},
        )
        return record

    def get(self, memory_id: str) -> MemoryRecord:
        for record in self.list():
            if record.id == memory_id:
                return record
        raise ForgeNotFoundError(f"memory not found: {memory_id}")

    def list(self, *, status: MemoryStatus | None = None) -> tuple[MemoryRecord, ...]:
        records: list[MemoryRecord] = []
        for kind in MemoryKind:
            records.extend(
                MemoryRecord.from_dict(value)
                for value in self.store.list_records(f"memory/{_kind_dir(kind)}")
            )
        selected = (record for record in records if status is None or record.status is status)
        return tuple(sorted(selected, key=lambda item: item.id))

    def decide(
        self,
        memory_id: str,
        *,
        accepted: bool,
        decided_by: str,
        reason: str,
        expected_revision: int,
    ) -> MemoryRecord:
        _require_human(decided_by)
        current = self.get(memory_id)
        if current.revision != expected_revision:
            raise ForgeConflictError(
                f"memory {memory_id} revision changed: expected {expected_revision}, "
                f"found {current.revision}"
            )
        if current.status is not MemoryStatus.draft:
            raise ForgeConflictError(f"memory {memory_id} is already {current.status.value}")
        updated = replace(
            current,
            status=MemoryStatus.accepted if accepted else MemoryStatus.rejected,
            decided_at=self.clock(),
            decided_by=_bounded(decided_by, "decided_by", 120),
            decision_reason=_bounded(reason, "reason", 2_000),
            revision=current.revision + 1,
        )
        self._replace(current, updated)
        self.audit.append(
            "memory.accepted" if accepted else "memory.rejected",
            actor=AuditActor.human,
            task_id=current.source_task_id,
            payload={"memory_id": memory_id, "revision": updated.revision},
        )
        return updated

    def supersede(
        self,
        memory_id: str,
        *,
        replacement_id: str,
        decided_by: str,
        reason: str,
        expected_revision: int,
    ) -> MemoryRecord:
        _require_human(decided_by)
        current = self.get(memory_id)
        replacement = self.get(replacement_id)
        if current.revision != expected_revision:
            raise ForgeConflictError("memory revision changed before supersede")
        if current.status is not MemoryStatus.accepted:
            raise ForgeConflictError("only accepted memory can be superseded")
        if replacement.status is not MemoryStatus.accepted or replacement.id == current.id:
            raise ForgeConflictError("replacement must be a different accepted memory")
        updated = replace(
            current,
            status=MemoryStatus.superseded,
            superseded_by=replacement.id,
            decided_at=self.clock(),
            decided_by=decided_by,
            decision_reason=_bounded(reason, "reason", 2_000),
            revision=current.revision + 1,
        )
        self._replace(current, updated)
        self.audit.append(
            "memory.superseded",
            actor=AuditActor.human,
            task_id=current.source_task_id,
            payload={"memory_id": current.id, "replacement_id": replacement.id},
        )
        return updated

    def select_for_task(
        self,
        task: ForgeTask,
        *,
        limit: int = SELECTION_COUNT,
        byte_limit: int = SELECTION_LIMIT,
        persist: bool = True,
    ) -> tuple[MemorySelection, tuple[MemoryRecord, ...]]:
        if not 1 <= limit <= SELECTION_COUNT or not 1_024 <= byte_limit <= SELECTION_LIMIT:
            raise ValueError("memory selection exceeds N3 hard limits")
        query = " ".join((task.title, task.objective, *task.related_modules))
        query_tokens = _tokens(query)
        ranked: list[tuple[int, tuple[str, ...], MemoryRecord]] = []
        for record in self.list(status=MemoryStatus.accepted):
            score, reasons = _rank(record, query_tokens, task.related_modules)
            if score > 0:
                ranked.append((score, reasons, record))
        ranked.sort(key=lambda item: (-item[0], item[2].id))
        selected: list[MemoryRecord] = []
        items: list[MemorySelectionItem] = []
        total = 0
        truncated = len(ranked) > limit
        for score, reasons, record in ranked:
            size = len(_render(record).encode("utf-8"))
            if len(selected) >= limit or total + size > byte_limit:
                truncated = True
                continue
            selected.append(record)
            items.append(
                MemorySelectionItem(
                    memory_id=record.id,
                    score=score,
                    reasons=reasons,
                    content_sha256=record.content_sha256,
                    size_bytes=size,
                )
            )
            total += size
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        selected_at = max(
            (task.updated_at, *(record.decided_at or record.created_at for record in selected))
        )
        canonical = json.dumps(
            [item.to_dict() for item in items], sort_keys=True, separators=(",", ":")
        )
        digest = hashlib.sha256(
            f"{task.id}:{task.revision}:{selected_at}:{query_hash}:{canonical}".encode()
        ).hexdigest()
        selection = MemorySelection(
            id=f"memory-selection-{digest[:24]}",
            task_id=task.id,
            created_at=selected_at,
            query_sha256=query_hash,
            items=tuple(items),
            total_bytes=total,
            truncated=truncated,
        )
        if persist:
            self.store.write_record(
                f"memory/selections/{task.id}/{selection.id}.json", selection.to_dict()
            )
            self.audit.append(
                "memory.selected",
                actor=AuditActor.system,
                task_id=task.id,
                payload={
                    "selection_id": selection.id,
                    "memory_ids": [item.memory_id for item in items],
                    "total_bytes": total,
                    "truncated": truncated,
                },
            )
        return selection, tuple(selected)

    def _replace(self, current: MemoryRecord, updated: MemoryRecord) -> None:
        path = self.store.forge_dir / _record_path(current)
        lock = self.store.forge_dir / "memory" / f".{current.id}.lock"
        with self.store.exclusive_lock(lock):
            actual = MemoryRecord.from_dict(self.store.read_json(path))
            if actual.revision != current.revision:
                raise ForgeConflictError("memory changed while acquiring lock")
            self.store.write_json(path, updated.to_dict())


def render_memory(record: MemoryRecord) -> str:
    """Render accepted memory as untrusted, bounded runtime evidence."""

    return _render(record)


def memory_source_path(record: MemoryRecord) -> str:
    """Return the repository-relative evidence path for a memory record."""

    return f".forge/{_record_path(record)}"


def _record_path(record: MemoryRecord) -> str:
    return f"memory/{_kind_dir(record.kind)}/{record.id}.json"


def _kind_dir(kind: MemoryKind) -> str:
    return {
        MemoryKind.decision: "decisions",
        MemoryKind.failure: "failures",
        MemoryKind.pattern: "patterns",
        MemoryKind.task: "tasks",
    }[kind]


def _render(record: MemoryRecord) -> str:
    payload = {
        "id": record.id,
        "kind": record.kind.value,
        "title": record.title,
        "body": _redact(record.body),
        "tags": list(record.tags),
        "related_modules": list(record.related_modules),
        "source_task_id": record.source_task_id,
        "source_report_id": record.source_report_id,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _rank(
    record: MemoryRecord, query: set[str], modules: tuple[str, ...]
) -> tuple[int, tuple[str, ...]]:
    fields = {
        "title": _tokens(record.title),
        "tags": _tokens(" ".join(record.tags)),
        "modules": _tokens(" ".join(record.related_modules)),
        "body": _tokens(record.body),
    }
    weights = {"title": 8, "tags": 6, "modules": 5, "body": 1}
    reasons: list[str] = []
    score = 0
    for name, tokens in fields.items():
        matches = query.intersection(tokens)
        if matches:
            score += len(matches) * weights[name]
            reasons.append(f"{name}:{','.join(sorted(matches)[:5])}")
    normalized_modules = {item.lower().replace("\\", "/") for item in modules}
    related = {item.lower().replace("\\", "/") for item in record.related_modules}
    if normalized_modules.intersection(related):
        score += 20
        reasons.append("exact-module")
    return score, tuple(reasons)


def _tokens(value: str) -> set[str]:
    return {
        item.lower() for item in re.findall(r"[\w\-./]+", value, flags=re.UNICODE) if len(item) > 1
    }


def _redact(value: str) -> str:
    patterns = (
        r"(?i)(authorization\s*[:=]\s*)(\S+)",
        r"(?i)((?:api[_-]?key|password|secret|token)\s*[:=]\s*)(\S+)",
    )
    result = value
    for pattern in patterns:
        result = re.sub(pattern, r"\1[REDACTED]", result)
    return result
