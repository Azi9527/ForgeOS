"""Read-only evidence graph and persisted-file integrity scans."""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from .audit import AuditActor, AuditLog
from .execution_records import ExecutionAttemptRepository
from .memory import MemoryService
from .policy import PolicyEngine
from .storage import ForgeStore

MAX_EVIDENCE_FILE_BYTES = 2_097_152


class IntegritySeverity(str, Enum):
    error = "ERROR"
    warning = "WARNING"


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    code: str
    severity: IntegritySeverity
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    id: str
    scanned_at: str
    passed: bool
    files_scanned: int
    objects_checked: int
    issues: tuple[IntegrityIssue, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "scanned_at": self.scanned_at,
            "passed": self.passed,
            "files_scanned": self.files_scanned,
            "objects_checked": self.objects_checked,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class IntegrityService:
    """Validate file safety, schemas, hashes and cross-object evidence links."""

    def __init__(self, store: ForgeStore, *, clock: Callable[[], str]) -> None:
        self.store = store
        self.clock = clock
        self.audit = AuditLog(store, clock=clock)

    def scan(self, *, persist: bool = False) -> IntegrityReport:
        issues: list[IntegrityIssue] = []
        files_scanned = self._scan_files(issues)
        objects_checked = 0
        tasks = ()
        try:
            tasks = self.store.list_tasks()
            objects_checked += len(tasks)
        except Exception as exc:
            issues.append(_issue("TASK_PARSE", ".forge/tasks", exc))
        try:
            self.audit.read_all()
            objects_checked += 1
        except Exception as exc:
            issues.append(_issue("AUDIT_CHAIN", ".forge/logs/audit.jsonl", exc))
        try:
            memories = MemoryService(self.store, clock=self.clock).list()
            objects_checked += len(memories)
        except Exception as exc:
            memories = ()
            issues.append(_issue("MEMORY_HASH", ".forge/memory", exc))
        try:
            rules = PolicyEngine(self.store, clock=self.clock).rules()
            objects_checked += len(rules)
        except Exception as exc:
            issues.append(_issue("POLICY_SCHEMA", ".forge/policies", exc))
        for task in tasks:
            try:
                attempts = ExecutionAttemptRepository(self.store).list_for_task(task.id)
                objects_checked += len(attempts)
            except Exception as exc:
                issues.append(
                    _issue(
                        "ATTEMPT_PARSE",
                        f".forge/execution-attempts/{task.id}",
                        exc,
                    )
                )
            self._check_task_links(task.to_dict(), issues)
        task_ids = {task.id for task in tasks}
        for memory in memories:
            if memory.source_task_id is not None and memory.source_task_id not in task_ids:
                issues.append(
                    IntegrityIssue(
                        "MEMORY_TASK_LINK",
                        IntegritySeverity.error,
                        f".forge/memory/{memory.id}",
                        f"source task does not exist: {memory.source_task_id}",
                    )
                )
        report = IntegrityReport(
            id=f"integrity-{uuid4()}",
            scanned_at=self.clock(),
            passed=not any(issue.severity is IntegritySeverity.error for issue in issues),
            files_scanned=files_scanned,
            objects_checked=objects_checked,
            issues=tuple(issues),
        )
        if persist:
            self.store.write_record(f"integrity/scans/{report.id}.json", report.to_dict())
            self.audit.append(
                "integrity.scan_completed",
                actor=AuditActor.system,
                payload={
                    "scan_id": report.id,
                    "passed": report.passed,
                    "files_scanned": files_scanned,
                    "error_count": sum(
                        issue.severity is IntegritySeverity.error for issue in issues
                    ),
                    "warning_count": sum(
                        issue.severity is IntegritySeverity.warning for issue in issues
                    ),
                },
            )
        return report

    def latest(self) -> dict[str, Any] | None:
        records = self.store.list_records("integrity/scans")
        return records[-1] if records else None

    def _scan_files(self, issues: list[IntegrityIssue]) -> int:
        count = 0
        for path in sorted(self.store.forge_dir.rglob("*")):
            relative = path.relative_to(self.store.project_root).as_posix()
            if path.is_symlink():
                issues.append(
                    IntegrityIssue(
                        "SYMLINK",
                        IntegritySeverity.error,
                        relative,
                        "Forge protocol paths must not be symbolic links",
                    )
                )
                continue
            if not path.is_file():
                continue
            count += 1
            if path.stat().st_size > MAX_EVIDENCE_FILE_BYTES:
                issues.append(
                    IntegrityIssue(
                        "FILE_SIZE",
                        IntegritySeverity.error,
                        relative,
                        f"file exceeds {MAX_EVIDENCE_FILE_BYTES} bytes",
                    )
                )
            if path.name.endswith(".tmp") or path.name.endswith(".lock"):
                issues.append(
                    IntegrityIssue(
                        "STALE_WORK_FILE",
                        IntegritySeverity.warning,
                        relative,
                        "temporary or lock file requires operator inspection",
                    )
                )
            if path.suffix == ".json" or path.name == "forge.yaml":
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(value, dict):
                        raise ValueError("top-level JSON value must be an object")
                    version = value.get("schema_version")
                    if version is not None and (not isinstance(version, int) or version < 1):
                        raise ValueError("schema_version must be a positive integer")
                except Exception as exc:
                    issues.append(_issue("JSON_SCHEMA", relative, exc))
        return count

    def _check_task_links(self, task: dict[str, Any], issues: list[IntegrityIssue]) -> None:
        task_id = str(task["id"])
        validation = task.get("validation")
        if isinstance(validation, dict):
            report_id = validation.get("report_id")
            reports = self.store.list_records("validation/results")
            if not any(report.get("report_id") == report_id for report in reports):
                issues.append(
                    IntegrityIssue(
                        "VALIDATION_LINK",
                        IntegritySeverity.error,
                        f".forge/tasks/{task_id}",
                        f"validation report does not exist: {report_id}",
                    )
                )
            regression_id = validation.get("regression_report_id")
            regressions = self.store.list_records("validation/regression")
            if regression_id is not None and not any(
                report.get("report_id") == regression_id for report in regressions
            ):
                issues.append(
                    IntegrityIssue(
                        "REGRESSION_LINK",
                        IntegritySeverity.error,
                        f".forge/tasks/{task_id}",
                        f"regression report does not exist: {regression_id}",
                    )
                )
        task_report_id = task.get("task_report_id")
        if task_report_id is not None:
            reports = self.store.list_records(f"reports/{task_id}")
            if not any(report.get("report_id") == task_report_id for report in reports):
                issues.append(
                    IntegrityIssue(
                        "TASK_REPORT_LINK",
                        IntegritySeverity.error,
                        f".forge/tasks/{task_id}",
                        f"Task Report does not exist: {task_report_id}",
                    )
                )


def _issue(code: str, path: str, error: Exception) -> IntegrityIssue:
    return IntegrityIssue(code, IntegritySeverity.error, path, str(error)[:2_000])
