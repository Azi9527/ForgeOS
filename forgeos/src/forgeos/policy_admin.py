"""Human-governed lifecycle for project-owned additive DENY policy files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .audit import AuditActor, AuditLog
from .errors import ForgeConflictError, ForgeNotFoundError
from .governance import validate_human_authority
from .policy import PolicyEngine, PolicyRule, PolicyTarget
from .storage import ForgeStore

_RULE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")


@dataclass(frozen=True, slots=True)
class ManagedPolicy:
    rule: PolicyRule
    built_in: bool
    active: bool
    source: str
    retired_at: str | None = None
    retired_by: str | None = None
    retirement_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.rule.to_dict(),
            "built_in": self.built_in,
            "active": self.active,
            "source": self.source,
            "retired_at": self.retired_at,
            "retired_by": self.retired_by,
            "retirement_reason": self.retirement_reason,
        }


class PolicyAdminService:
    """Create or retire project rules while preserving retired evidence."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def list(self) -> tuple[ManagedPolicy, ...]:
        active_values = self.store.list_records("policies")
        active_rules = [PolicyRule.from_dict(value) for value in active_values]
        active_ids = {rule.id for rule in active_rules}
        built_ins = [
            ManagedPolicy(rule, True, True, "builtin")
            for rule in PolicyEngine(self.store, clock=self.clock).rules()
            if rule.id not in active_ids
        ]
        active = [ManagedPolicy(rule, False, True, "project") for rule in active_rules]
        retired = []
        for value in self.store.list_records("policies/retired"):
            retired.append(
                ManagedPolicy(
                    PolicyRule.from_dict(value),
                    False,
                    False,
                    "project",
                    retired_at=_optional_text(value, "retired_at"),
                    retired_by=_optional_text(value, "retired_by"),
                    retirement_reason=_optional_text(value, "retirement_reason"),
                )
            )
        return tuple(
            sorted(
                (*built_ins, *active, *retired), key=lambda item: (item.rule.id, not item.active)
            )
        )

    def create(
        self,
        *,
        rule_id: str,
        name: str,
        target: PolicyTarget,
        patterns: tuple[str, ...],
        reason: str,
        created_by: str,
    ) -> ManagedPolicy:
        validate_human_authority(created_by, "Policy creation")
        if _RULE_ID.fullmatch(rule_id) is None:
            raise ValueError("policy id must use letters, digits, dots, underscores, or hyphens")
        rule = PolicyRule.from_dict(
            {
                "schema_version": 1,
                "id": rule_id,
                "name": name,
                "effect": "DENY",
                "target": target.value,
                "patterns": list(patterns),
                "reason": reason,
            }
        )
        if any(item.rule.id == rule.id for item in self.list()):
            raise ForgeConflictError(f"policy id already exists: {rule.id}")
        self.store.write_record(f"policies/{rule.id}.json", rule.to_dict())
        self.audit.append(
            "policy.created",
            actor=AuditActor.human,
            payload={"rule_id": rule.id, "created_by": created_by},
        )
        return ManagedPolicy(rule, False, True, "project")

    def retire(self, rule_id: str, *, retired_by: str, reason: str) -> ManagedPolicy:
        validate_human_authority(retired_by, "Policy retirement")
        current = next(
            (item for item in self.list() if item.rule.id == rule_id and item.active),
            None,
        )
        if current is None:
            raise ForgeNotFoundError(f"active policy not found: {rule_id}")
        if current.built_in:
            raise ForgeConflictError("built-in ForgePolicy rules cannot be retired")
        source = self._active_path(rule_id)
        target = self.store.forge_dir / "policies" / "retired" / source.name
        retired = {
            **current.rule.to_dict(),
            "retired_at": self.clock(),
            "retired_by": retired_by.strip(),
            "retirement_reason": reason.strip(),
        }
        if not retired["retirement_reason"]:
            raise ValueError("policy retirement reason must not be empty")
        lock = self.store.forge_dir / "policies" / f".{rule_id}.lock"
        with self.store.exclusive_lock(lock):
            if target.exists():
                raise ForgeConflictError(f"retired policy already exists: {rule_id}")
            self.store.write_json(target, retired)
            Path(source).unlink()
        self.audit.append(
            "policy.retired",
            actor=AuditActor.human,
            payload={"rule_id": rule_id, "retired_by": retired_by},
        )
        return ManagedPolicy(
            current.rule,
            False,
            False,
            "project",
            retired_at=retired["retired_at"],
            retired_by=retired["retired_by"],
            retirement_reason=retired["retirement_reason"],
        )

    def _active_path(self, rule_id: str) -> Path:
        directory = self.store.forge_dir / "policies"
        for path in sorted(directory.glob("*.json")):
            if PolicyRule.from_dict(self.store.read_json(path)).id == rule_id:
                return path
        raise ForgeNotFoundError(f"active policy file not found: {rule_id}")


def _optional_text(value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item if isinstance(item, str) and item else None
