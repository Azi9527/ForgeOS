"""Read-only ForgeOS environment and workspace diagnostics."""

import importlib.metadata
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from .execution_records import AttemptState, ExecutionAttemptRepository
from .git_evidence import GitEvidenceService
from .integrity import IntegrityService
from .memory import MemoryService
from .migration import ProtocolMigrator
from .policy import PolicyEngine
from .release import ReleaseReadinessService
from .service import ForgeService, utc_now
from .validation_types import ValidationLevel


class DoctorStatus(str, Enum):
    """Stable diagnostic result levels."""

    passed = "PASS"
    warning = "WARN"
    failed = "FAIL"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One non-mutating diagnostic with actionable detail."""

    name: str
    status: DoctorStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Complete read-only diagnostic report for one workspace."""

    workspace: str
    checks: tuple[DoctorCheck, ...]
    schema_version: int = 1

    @property
    def passed(self) -> bool:
        return all(check.status is not DoctorStatus.failed for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workspace": self.workspace,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }


class ForgeDoctor:
    """Inspect config, store, Git and SDK prerequisites without writing files."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def run(self) -> DoctorReport:
        checks: list[DoctorCheck] = []
        if not self.workspace.is_dir():
            checks.append(
                DoctorCheck("workspace", DoctorStatus.failed, "workspace directory does not exist")
            )
            return DoctorReport(str(self.workspace), tuple(checks))
        checks.append(DoctorCheck("workspace", DoctorStatus.passed, "workspace is accessible"))
        forge = ForgeService(self.workspace, ensure_layout=False)
        if not forge.store.is_initialized():
            checks.append(
                DoctorCheck("forge_config", DoctorStatus.failed, "run `forge init` first")
            )
        else:
            self._check_forge(forge, checks)
        self._check_git(checks)
        self._check_sdk(checks)
        return DoctorReport(str(self.workspace), tuple(checks))

    def _check_forge(self, forge: ForgeService, checks: list[DoctorCheck]) -> None:
        try:
            config = forge.config()
            forge.audit.read_all()
        except Exception as exc:
            checks.append(
                DoctorCheck("forge_config", DoctorStatus.failed, f"invalid Forge state: {exc}")
            )
            return
        checks.append(
            DoctorCheck(
                "forge_config",
                DoctorStatus.passed,
                f"schema {config.schema_version}; project {config.project.name}",
            )
        )
        required = (
            "tasks/active",
            "validation/results",
            "validation/baselines",
            "validation/regression",
            "logs",
            "executions",
            "execution-attempts",
            "evidence/git",
            "context/packages",
            "reports",
            "rules",
            "memory/tasks",
            "memory/selections",
            "policies",
            "policies/retired",
            "policy/evaluations",
            "budget/evaluations",
            "recovery/cancellations",
            "recovery/runs",
            "integrity/scans",
            "migrations",
            "release/checks",
            "exports",
            "imports",
        )
        missing = [item for item in required if not (forge.store.forge_dir / item).is_dir()]
        checks.append(
            DoctorCheck(
                "forge_layout",
                DoctorStatus.failed if missing else DoctorStatus.passed,
                f"missing directories: {', '.join(missing)}" if missing else "layout is complete",
            )
        )
        try:
            memories = MemoryService(forge.store, clock=utc_now).list()
            policies = PolicyEngine(forge.store, clock=utc_now).rules()
            checks.append(
                DoctorCheck(
                    "memory_policy",
                    DoctorStatus.passed,
                    f"{len(memories)} memory records; {len(policies)} active policy rules",
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    "memory_policy",
                    DoctorStatus.failed,
                    f"invalid N3 memory/policy state: {exc}",
                )
            )
        configured_levels = {check.level for check in config.validation_checks if check.required}
        missing_levels = []
        if ValidationLevel.build not in configured_levels:
            missing_levels.append(ValidationLevel.build.value)
        if not configured_levels.intersection({ValidationLevel.unit, ValidationLevel.integration}):
            missing_levels.append("L2_UNIT_OR_L3_INTEGRATION")
        checks.append(
            DoctorCheck(
                "validation_coverage",
                DoctorStatus.warning if missing_levels else DoctorStatus.passed,
                (
                    f"missing required command coverage: {', '.join(missing_levels)}"
                    if missing_levels
                    else "required build and test command coverage is configured"
                ),
            )
        )
        migration = ProtocolMigrator(forge.store, clock=utc_now).plan()
        checks.append(
            DoctorCheck(
                "protocol_migration",
                DoctorStatus.warning if migration.required else DoctorStatus.passed,
                (
                    f"migration required: {len(migration.actions)} additive actions"
                    if migration.required
                    else f"protocol version {migration.to_version} is current"
                ),
            )
        )
        integrity = IntegrityService(forge.store, clock=utc_now).scan()
        checks.append(
            DoctorCheck(
                "evidence_integrity",
                DoctorStatus.passed if integrity.passed else DoctorStatus.failed,
                (
                    f"{integrity.files_scanned} files; {integrity.objects_checked} objects; "
                    f"{len(integrity.issues)} issues"
                ),
            )
        )
        attempts = ExecutionAttemptRepository(forge.store)
        incomplete = [
            attempt
            for task in forge.tasks()
            for attempt in attempts.list_for_task(task.id)
            if attempt.status
            in {
                AttemptState.queued,
                AttemptState.running,
                AttemptState.interrupting,
            }
        ]
        checks.append(
            DoctorCheck(
                "execution_recovery",
                DoctorStatus.warning if incomplete else DoctorStatus.passed,
                (
                    f"{len(incomplete)} incomplete attempts require recovery"
                    if incomplete
                    else "no incomplete persisted attempts"
                ),
            )
        )
        release = ReleaseReadinessService(forge.store, clock=utc_now).check(persist=False)
        checks.append(
            DoctorCheck(
                "release_contract",
                DoctorStatus.passed if release.passed else DoctorStatus.failed,
                f"package {release.package_version}; {len(release.checks)} release gates",
            )
        )

    def _check_git(self, checks: list[DoctorCheck]) -> None:
        snapshot = GitEvidenceService(self.workspace, clock=utc_now).capture(
            "DOCTOR",
            kind="diagnostic",
        )
        checks.append(
            DoctorCheck(
                "git",
                DoctorStatus.passed if snapshot.available else DoctorStatus.warning,
                (
                    f"HEAD {snapshot.head}; branch {snapshot.branch or '(detached)'}"
                    if snapshot.available
                    else snapshot.warning or "Git evidence unavailable"
                ),
            )
        )

    def _check_sdk(self, checks: list[DoctorCheck]) -> None:
        try:
            version = importlib.metadata.version("openai-codex")
            __import__("openai_codex")
        except (ImportError, importlib.metadata.PackageNotFoundError):
            checks.append(
                DoctorCheck(
                    "codex_sdk",
                    DoctorStatus.failed,
                    "install the forgeos-harness dependencies or `pip install openai-codex`",
                )
            )
            return
        checks.append(DoctorCheck("codex_sdk", DoctorStatus.passed, f"openai-codex {version}"))
        codex = shutil.which("codex")
        checks.append(
            DoctorCheck(
                "codex_cli",
                DoctorStatus.passed if codex else DoctorStatus.warning,
                codex or "standalone codex command not on PATH; SDK bundled runtime may still work",
            )
        )
