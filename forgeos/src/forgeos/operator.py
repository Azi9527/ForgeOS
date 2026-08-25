"""Application facade for N5 release and operator-management services."""

from __future__ import annotations

from typing import Any, Mapping

from ._control_payload import required_text
from .audit import AuditActor
from .audit_query import AuditQueryService
from .policy import PolicyTarget
from .policy_admin import PolicyAdminService
from .release import PACKAGE_VERSION, ReleaseReadinessService
from .service import ForgeService


class ForgeOperator:
    """Project-level release, audit, and policy operations for adapters."""

    def __init__(self, forge: ForgeService) -> None:
        self.forge = forge
        self.release = ReleaseReadinessService(forge.store, clock=forge.clock)
        self.audit = AuditQueryService(forge.audit)
        self.policies = PolicyAdminService(forge.store, clock=forge.clock)

    def status(self) -> dict[str, Any]:
        memory_count = sum(
            len(self.forge.store.list_records(f"memory/{kind}"))
            for kind in ("decisions", "failures", "patterns", "tasks")
        )
        return {
            "package_version": PACKAGE_VERSION,
            "release": self.release.latest(),
            "fixtures": self.release.fixture_status(),
            "policy_count": len(self.policies.list()),
            "memory_count": memory_count,
            "audit_event_types": list(self.audit.event_types()),
        }

    def release_check(self) -> dict[str, Any]:
        return self.release.check().to_dict()

    def audit_query(
        self,
        *,
        task_id: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        parsed_actor = AuditActor(actor) if actor else None
        return self.audit.query(
            task_id=task_id,
            event_type=event_type,
            actor=parsed_actor,
            after_sequence=after_sequence,
            limit=limit,
        ).to_dict()

    def list_policies(self) -> dict[str, Any]:
        return {"policies": [item.to_dict() for item in self.policies.list()]}

    def create_policy(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        patterns = payload.get("patterns")
        if not isinstance(patterns, list) or not all(isinstance(item, str) for item in patterns):
            raise ValueError("patterns must be an array of strings")
        return self.policies.create(
            rule_id=required_text(payload, "id"),
            name=required_text(payload, "name"),
            target=PolicyTarget(required_text(payload, "target")),
            patterns=tuple(patterns),
            reason=required_text(payload, "reason"),
            created_by=required_text(payload, "created_by"),
        ).to_dict()

    def retire_policy(self, rule_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self.policies.retire(
            rule_id,
            retired_by=required_text(payload, "retired_by"),
            reason=required_text(payload, "reason"),
        ).to_dict()
