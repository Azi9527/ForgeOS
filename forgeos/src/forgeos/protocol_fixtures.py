"""Bundled v1 protocol examples used as release compatibility fixtures."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any, Callable

from .config import ForgeConfig
from .migration import CURRENT_PROTOCOL_VERSION
from .models import ForgeTask
from .policy import PolicyRule


@dataclass(frozen=True, slots=True)
class FixtureResult:
    name: str
    sha256: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sha256": self.sha256,
            "passed": self.passed,
            "detail": self.detail,
        }


class ProtocolFixtureVerifier:
    """Round-trip canonical protocol fixtures through current v1 parsers."""

    def verify(self) -> tuple[FixtureResult, ...]:
        parsers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "forge_config.json": lambda value: ForgeConfig.from_dict(value).to_dict(),
            "task_created.json": lambda value: ForgeTask.from_dict(value).to_dict(),
            "policy_deny.json": lambda value: PolicyRule.from_dict(value).to_dict(),
            "protocol.json": _protocol,
        }
        results: list[FixtureResult] = []
        root = files("forgeos").joinpath("protocol_fixtures", "v1")
        for name, parser in parsers.items():
            raw = root.joinpath(name).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()
            try:
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("fixture root must be an object")
                normalized = parser(value)
                passed = normalized == value
                detail = "canonical round-trip" if passed else "round-trip changed fixture"
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                passed = False
                detail = str(exc)
            results.append(FixtureResult(name, digest, passed, detail))
        return tuple(results)


def _protocol(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != 1:
        raise ValueError("protocol fixture schema_version must be 1")
    if value.get("protocol_version") != CURRENT_PROTOCOL_VERSION:
        raise ValueError("protocol fixture does not match current protocol version")
    return value
