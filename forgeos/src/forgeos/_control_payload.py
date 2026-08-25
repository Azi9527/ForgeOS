"""Private payload parsing and workflow projection helpers for Control API."""

from collections.abc import Mapping
from typing import Any

from .workflow import WorkflowResult


def workflow_result(result: WorkflowResult) -> dict[str, Any]:
    return {
        "task": result.task.to_dict(),
        "validation_report": (
            result.validation_report.to_dict() if result.validation_report is not None else None
        ),
        "regression_report": (
            result.regression_report.to_dict() if result.regression_report is not None else None
        ),
    }


def required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def optional_text(payload: Mapping[str, Any], key: str, *, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value.strip()


def optional_nullable_text(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be null or a string")
    return value.strip() or None


def optional_int(payload: Mapping[str, Any], key: str, *, default: int) -> int:
    value = payload.get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def required_int(payload: Mapping[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def required_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def string_items(
    payload: Mapping[str, Any], key: str, *, required: bool = False
) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{key} must be an array of strings")
    items = tuple(item.strip() for item in value if item.strip())
    if required and not items:
        raise ValueError(f"{key} must contain at least one item")
    return items


def object_items(
    payload: Mapping[str, Any], key: str, *, required: bool = False
) -> tuple[dict[str, Any], ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{key} must be an array of objects")
    items = tuple(dict(item) for item in value)
    if required and not items:
        raise ValueError(f"{key} must contain at least one item")
    return items
