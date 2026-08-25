"""Release-readiness gates for the ForgeOS Python control layer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from importlib.resources import files
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .audit_query import AuditQueryService
from .errors import ForgeError, ForgeReleaseError
from .integrity import IntegrityService
from .memory import MemoryService
from .migration import CURRENT_PROTOCOL_VERSION, ProtocolMigrator
from .policy import PolicyEngine
from .protocol_fixtures import ProtocolFixtureVerifier
from .storage import ForgeStore

PACKAGE_VERSION = "0.2.0"


class ReleaseCheckStatus(str, Enum):
    passed = "PASS"
    failed = "FAIL"


@dataclass(frozen=True, slots=True)
class ReleaseCheck:
    name: str
    status: ReleaseCheckStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    id: str
    checked_at: str
    package_version: str
    protocol_version: int
    checks: tuple[ReleaseCheck, ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return all(check.status is ReleaseCheckStatus.passed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "checked_at": self.checked_at,
            "package_version": self.package_version,
            "protocol_version": self.protocol_version,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }


class ReleaseReadinessService:
    """Evaluate deterministic protocol, integrity, and packaging contracts."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def check(self, *, persist: bool = True) -> ReleaseReport:
        checks = (
            self._manifest_check(),
            self._fixture_check(),
            self._migration_check(),
            self._integrity_check(),
            self._domain_check(),
            self._assets_check(),
        )
        report = ReleaseReport(
            id=f"release-check-{uuid4()}",
            checked_at=self.clock(),
            package_version=PACKAGE_VERSION,
            protocol_version=CURRENT_PROTOCOL_VERSION,
            checks=checks,
        )
        if persist:
            self.store.write_record(f"release/checks/{report.id}.json", report.to_dict())
            self.audit.append(
                "release.readiness_checked",
                actor=AuditActor.system,
                payload={"report_id": report.id, "passed": report.passed},
            )
        return report

    def latest(self) -> dict[str, Any] | None:
        records = self.store.list_records("release/checks")
        return records[-1] if records else None

    def fixture_status(self) -> dict[str, Any]:
        results = ProtocolFixtureVerifier().verify()
        return {
            "protocol_version": CURRENT_PROTOCOL_VERSION,
            "passed": all(result.passed for result in results),
            "fixtures": [result.to_dict() for result in results],
        }

    def _manifest_check(self) -> ReleaseCheck:
        try:
            raw = files("forgeos").joinpath("release_manifest.json").read_text(encoding="utf-8")
            manifest = json.loads(raw)
            expected = {
                "schema_version": 1,
                "package_version": PACKAGE_VERSION,
                "protocol_version": CURRENT_PROTOCOL_VERSION,
                "bundle_schema_version": 1,
                "supported_codex_sdk": ">=0.146,<0.148",
            }
            if manifest != expected:
                raise ForgeReleaseError("release_manifest.json does not match runtime constants")
            return _pass("release_manifest", f"package {PACKAGE_VERSION}; protocol v1")
        except (ForgeError, OSError, ValueError, json.JSONDecodeError) as exc:
            return _fail("release_manifest", str(exc))

    def _fixture_check(self) -> ReleaseCheck:
        results = ProtocolFixtureVerifier().verify()
        failures = [result.name for result in results if not result.passed]
        return (
            _fail("protocol_fixtures", f"failed: {', '.join(failures)}")
            if failures
            else _pass("protocol_fixtures", f"{len(results)} canonical v1 fixtures")
        )

    def _migration_check(self) -> ReleaseCheck:
        try:
            plan = ProtocolMigrator(self.store, clock=self.clock).plan()
            if plan.required:
                return _fail("protocol_migration", "; ".join(plan.actions))
            return _pass("protocol_migration", "workspace protocol is current")
        except (ForgeError, OSError, ValueError) as exc:
            return _fail("protocol_migration", str(exc))

    def _integrity_check(self) -> ReleaseCheck:
        try:
            report = IntegrityService(self.store, clock=self.clock).scan(persist=False)
            return (
                _pass("evidence_integrity", f"{report.files_scanned} files; 0 issues")
                if report.passed
                else _fail("evidence_integrity", f"{len(report.issues)} issues")
            )
        except (ForgeError, OSError, ValueError) as exc:
            return _fail("evidence_integrity", str(exc))

    def _domain_check(self) -> ReleaseCheck:
        try:
            self.store.load_config()
            self.store.list_tasks()
            MemoryService(self.store, clock=self.clock).list()
            PolicyEngine(self.store, clock=self.clock).rules()
            AuditQueryService(self.audit).query(limit=1)
            return _pass("domain_readback", "config/task/memory/policy/audit readable")
        except (ForgeError, OSError, ValueError) as exc:
            return _fail("domain_readback", str(exc))

    def _assets_check(self) -> ReleaseCheck:
        root = files("forgeos").joinpath("web")
        missing = [
            name
            for name in ("index.html", "app.js", "operator.js", "styles.css")
            if not root.joinpath(name).is_file()
        ]
        return (
            _fail("operator_assets", f"missing: {', '.join(missing)}")
            if missing
            else _pass("operator_assets", "HTML/CSS/JS assets bundled")
        )


def _pass(name: str, detail: str) -> ReleaseCheck:
    return ReleaseCheck(name, ReleaseCheckStatus.passed, detail)


def _fail(name: str, detail: str) -> ReleaseCheck:
    return ReleaseCheck(name, ReleaseCheckStatus.failed, detail[:2_000])
