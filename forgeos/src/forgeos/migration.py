"""Additive, explicit `.forge` protocol migration planning and application."""

from dataclasses import dataclass
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .errors import ForgeConfigError
from .storage import ForgeStore

CURRENT_PROTOCOL_VERSION = 1
_PROTOCOL_PATHS = (
    "budget/evaluations",
    "recovery/cancellations",
    "recovery/runs",
    "integrity/scans",
    "migrations",
    "policies/retired",
    "release/checks",
    "exports",
    "imports",
)


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    from_version: int
    to_version: int
    required: bool
    actions: tuple[str, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "required": self.required,
            "actions": list(self.actions),
        }


@dataclass(frozen=True, slots=True)
class MigrationRecord:
    id: str
    applied_at: str
    from_version: int
    to_version: int
    actions: tuple[str, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "applied_at": self.applied_at,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "actions": list(self.actions),
        }


class ProtocolMigrator:
    """Create only missing protocol state; never rewrite authoritative objects."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def plan(self) -> MigrationPlan:
        manifest = self._manifest()
        from_version = 0 if manifest is None else _version(manifest)
        if from_version > CURRENT_PROTOCOL_VERSION:
            raise ForgeConfigError(
                f"Forge protocol {from_version} is newer than supported {CURRENT_PROTOCOL_VERSION}"
            )
        actions = [
            f"create directory .forge/{path}"
            for path in _PROTOCOL_PATHS
            if not (self.store.forge_dir / path).is_dir()
        ]
        if from_version < CURRENT_PROTOCOL_VERSION:
            actions.append(f"write protocol manifest version {CURRENT_PROTOCOL_VERSION}")
        return MigrationPlan(
            from_version=from_version,
            to_version=CURRENT_PROTOCOL_VERSION,
            required=bool(actions),
            actions=tuple(actions),
        )

    def apply(self) -> MigrationRecord:
        plan = self.plan()
        self.store.ensure_layout()
        if plan.from_version < CURRENT_PROTOCOL_VERSION:
            self.store.write_record(
                "protocol.json",
                {
                    "schema_version": 1,
                    "protocol_version": CURRENT_PROTOCOL_VERSION,
                    "updated_at": self.clock(),
                },
            )
        record = MigrationRecord(
            id=f"migration-{uuid4()}",
            applied_at=self.clock(),
            from_version=plan.from_version,
            to_version=plan.to_version,
            actions=plan.actions,
        )
        self.store.write_record(f"migrations/{record.id}.json", record.to_dict())
        self.audit.append(
            "protocol.migration_applied",
            actor=AuditActor.system,
            payload={
                "migration_id": record.id,
                "from_version": record.from_version,
                "to_version": record.to_version,
                "actions": list(record.actions),
            },
        )
        return record

    def _manifest(self) -> dict[str, Any] | None:
        path = self.store.forge_dir / "protocol.json"
        return self.store.read_json(path) if path.exists() else None


def _version(value: dict[str, Any]) -> int:
    version = value.get("protocol_version")
    if not isinstance(version, int) or version < 1:
        raise ForgeConfigError("protocol_version must be a positive integer")
    return version
