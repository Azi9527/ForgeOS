"""Private bounded-value and canonical-hash helpers for memory records."""

import hashlib
import json
from typing import Any

from .errors import ForgeConflictError


def content_hash(
    kind: str, title: str, body: str, tags: tuple[str, ...], modules: tuple[str, ...]
) -> str:
    value = json.dumps(
        {"kind": kind, "title": title, "body": body, "tags": tags, "modules": modules},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def bounded(value: str, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    normalized = value.strip()
    if len(normalized.encode("utf-8")) > maximum:
        raise ValueError(f"{field} exceeds {maximum} UTF-8 bytes")
    return normalized


def bounded_items(
    values: tuple[str, ...], field: str, count_maximum: int, byte_maximum: int
) -> tuple[str, ...]:
    if len(values) > count_maximum:
        raise ValueError(f"{field} exceeds {count_maximum} items")
    return tuple(bounded(item, field, byte_maximum) for item in values)


def text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} must be a non-empty string")
    return item


def optional_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is not None and (not isinstance(item, str) or not item):
        raise ValueError(f"{key} must be null or a non-empty string")
    return item


def strings(value: dict[str, Any], key: str) -> tuple[str, ...]:
    items = value.get(key)
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise ValueError(f"{key} must be an array of strings")
    return tuple(items)


def non_negative(value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int) or item < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return item


def is_non_human(actor: str) -> bool:
    normalized = actor.strip().lower()
    return any(
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
    )


def require_human(actor: str) -> None:
    if is_non_human(actor):
        raise ForgeConflictError("non-human identities cannot decide engineering memory")
    bounded(actor, "human authority", 120)
