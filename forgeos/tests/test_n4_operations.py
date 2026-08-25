import json
import sys
from pathlib import Path

import pytest

from forgeos.audit import AuditActor
from forgeos.budget import BudgetService
from forgeos.cli import main
from forgeos.config import ValidationCheckConfig
from forgeos.errors import ForgeBudgetError, ForgeConfigError, ForgeConflictError
from forgeos.execution import ForgeExecutionService
from forgeos.execution_records import AttemptState, ExecutionAttemptRepository
from forgeos.integrity import IntegrityService
from forgeos.memory import MemoryKind, MemoryService
from forgeos.migration import CURRENT_PROTOCOL_VERSION, ProtocolMigrator
from forgeos.models import TaskStatus, TaskType
from forgeos.operations import ForgeOperations
from forgeos.recovery import CancellationService, RecoveryService
from forgeos.service import ForgeService
from forgeos.validation import ValidationRunner
from forgeos.validation_types import ValidationLevel
from forgeos.workflow import ForgeWorkflowService

NOW = "2026-08-25T00:00:00Z"


class UnusedGateway:
    def run_turn(self, *_args, **_kwargs):
        raise AssertionError("budget/cancellation gate must run before Codex")


def service(
    tmp_path: Path,
    *,
    attempt_limit: int = 8,
    checks: tuple[ValidationCheckConfig, ...] = (),
) -> ForgeService:
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    forge.init_project(
        name="N4",
        validation_checks=checks,
        execution_attempt_limit=attempt_limit,
    )
    return forge


def task(forge: ForgeService):
    return forge.create_task(
        title="Recover workflow",
        task_type=TaskType.fix,
        objective="Make workflow recovery explicit",
        acceptance_criteria=("recovery evidence exists",),
    )


def implementing(forge: ForgeService, task_id: str):
    current = forge.task(task_id)
    for status in (TaskStatus.analyzing, TaskStatus.planned, TaskStatus.implementing):
        current = forge.transition_task(
            task_id,
            status,
            expected_revision=current.revision,
            reason="test setup",
            actor=AuditActor.system,
        )
    return current


def test_budget_exhaustion_blocks_before_baseline_or_codex(tmp_path: Path) -> None:
    forge = service(tmp_path, attempt_limit=1)
    current = task(forge)
    attempts = ExecutionAttemptRepository(forge.store)
    attempt = attempts.create(task_id=current.id, kind="run", created_at=NOW)
    attempt = attempts.start(attempt, started_at=NOW)
    attempts.finish(attempt, status=AttemptState.interrupted, finished_at=NOW)
    workflow = ForgeWorkflowService(
        forge,
        ForgeExecutionService(forge, UnusedGateway()),
        ValidationRunner(tmp_path, clock=lambda: NOW),
    )

    with pytest.raises(ForgeBudgetError, match="1/1"):
        workflow.run_and_validate(current.id)

    blocked = forge.task(current.id)
    evidence = BudgetService(forge.store, clock=lambda: NOW).for_task(current.id)
    assert blocked.status is TaskStatus.blocked
    assert blocked.blocked_from is TaskStatus.created
    assert evidence[-1]["passed"] is False
    assert forge.store.list_records("validation/results") == ()


def test_cancellation_is_human_durable_idempotent_and_terminal(tmp_path: Path) -> None:
    forge = service(tmp_path)
    current = task(forge)
    cancellations = CancellationService(forge.store, clock=lambda: NOW)

    with pytest.raises(ForgeConflictError, match="cannot authorize"):
        cancellations.request(current, requested_by="codex-agent", reason="self cancel")
    requested = cancellations.request(
        current,
        requested_by="maintainer",
        reason="requirement was withdrawn",
    )
    assert (
        cancellations.request(
            current,
            requested_by="maintainer",
            reason="requirement was withdrawn",
        )
        == requested
    )
    cancelled = cancellations.apply(forge, current)

    assert cancelled is not None
    assert cancelled.status is TaskStatus.cancelled
    assert cancellations.for_task(current.id).status.value == "APPLIED"
    assert ForgeService(tmp_path, clock=lambda: NOW).task(current.id) == cancelled


def test_execution_applies_pending_cancellation_before_codex(tmp_path: Path) -> None:
    forge = service(tmp_path)
    current = task(forge)
    CancellationService(forge.store, clock=lambda: NOW).request(
        current,
        requested_by="maintainer",
        reason="stop before execution",
    )

    result = ForgeExecutionService(forge, UnusedGateway()).run_task(current.id)

    assert result.status is TaskStatus.cancelled
    assert ExecutionAttemptRepository(forge.store).list_for_task(current.id) == ()


def test_startup_recovery_interrupts_attempt_and_blocks_task(tmp_path: Path) -> None:
    forge = service(tmp_path)
    current = task(forge)
    current = implementing(forge, current.id)
    attempts = ExecutionAttemptRepository(forge.store)
    running = attempts.create(task_id=current.id, kind="run", created_at=NOW)
    attempts.start(running, started_at=NOW)

    report = RecoveryService(forge).recover()

    recovered = attempts.load(current.id, running.id)
    blocked = forge.task(current.id)
    assert recovered.status is AttemptState.interrupted
    assert blocked.status is TaskStatus.blocked
    assert blocked.blocked_from is TaskStatus.implementing
    assert report.interrupted_attempt_ids == (running.id,)
    assert report.blocked_task_ids == (current.id,)


def test_startup_recovery_honors_pending_cancellation(tmp_path: Path) -> None:
    forge = service(tmp_path)
    current = task(forge)
    current = implementing(forge, current.id)
    attempts = ExecutionAttemptRepository(forge.store)
    running = attempts.create(task_id=current.id, kind="run", created_at=NOW)
    attempts.start(running, started_at=NOW)
    CancellationService(forge.store, clock=lambda: NOW).request(
        current,
        requested_by="owner",
        reason="cancel despite process loss",
    )

    report = RecoveryService(forge).recover()

    assert forge.task(current.id).status is TaskStatus.cancelled
    assert report.cancelled_task_ids == (current.id,)


def test_integrity_scan_detects_memory_tampering_and_persists_evidence(tmp_path: Path) -> None:
    forge = service(tmp_path)
    memory = MemoryService(forge.store, clock=lambda: NOW)
    record = memory.create(
        kind=MemoryKind.decision,
        title="Integrity decision",
        body="Original evidence",
        created_by="maintainer",
    )
    integrity = IntegrityService(forge.store, clock=lambda: NOW)
    assert integrity.scan().passed is True
    path = forge.store.forge_dir / "memory" / "decisions" / f"{record.id}.json"
    tampered = forge.store.read_json(path)
    tampered["body"] = "Tampered without updating hash"
    forge.store.write_json(path, tampered)

    report = integrity.scan(persist=True)

    assert report.passed is False
    assert any(issue.code == "MEMORY_HASH" for issue in report.issues)
    assert integrity.latest()["id"] == report.id


def test_integrity_scan_detects_broken_task_report_link(tmp_path: Path) -> None:
    forge = service(tmp_path)
    current = task(forge)
    task_path = forge.store.forge_dir / "tasks" / "active" / f"{current.id}.json"
    value = forge.store.read_json(task_path)
    value["task_report_id"] = "missing-report"
    forge.store.write_json(task_path, value)

    report = IntegrityService(forge.store, clock=lambda: NOW).scan()

    assert report.passed is False
    assert any(issue.code == "TASK_REPORT_LINK" for issue in report.issues)


def test_protocol_migration_is_additive_idempotent_and_rejects_future(tmp_path: Path) -> None:
    forge = service(tmp_path)
    manifest = forge.store.forge_dir / "protocol.json"
    manifest.unlink()
    migrator = ProtocolMigrator(forge.store, clock=lambda: NOW)
    plan = migrator.plan()
    applied = migrator.apply()

    assert plan.required is True
    assert applied.from_version == 0
    assert migrator.plan().required is False
    assert forge.store.read_json(manifest)["protocol_version"] == CURRENT_PROTOCOL_VERSION

    forge.store.write_json(
        manifest,
        {"schema_version": 1, "protocol_version": 999, "updated_at": NOW},
    )
    with pytest.raises(ForgeConfigError, match="newer than supported"):
        migrator.plan()


def test_cli_operational_commands(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "init",
                "--name",
                "N4 CLI",
                "--attempt-limit",
                "4",
            )
        )
        == 0
    )
    capsys.readouterr()
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    current = task(forge)

    assert main(("--workspace", str(tmp_path), "budget", current.id)) == 0
    budget = json.loads(capsys.readouterr().out)
    assert budget["execution_attempt_limit"] == 4
    assert main(("--workspace", str(tmp_path), "integrity", "scan")) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True
    assert main(("--workspace", str(tmp_path), "migrate", "status")) == 0
    assert json.loads(capsys.readouterr().out)["required"] is False
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "cancel",
                current.id,
                "--requested-by",
                "owner",
                "--reason",
                "cancel from CLI",
            )
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["task"]["status"] == "CANCELLED"


def test_operations_facade_projects_task_evidence(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="unit",
        level=ValidationLevel.unit,
        argv=(sys.executable, "-c", "pass"),
    )
    forge = service(tmp_path, checks=(check,))
    current = task(forge)
    operations = ForgeOperations(forge)
    budget = operations.budget.evaluate(current)
    scan = operations.integrity_scan()
    detail = operations.task_evidence(current.id)

    assert detail["budgets"][-1]["id"] == budget.id
    assert detail["integrity"]["id"] == scan["id"]
    assert detail["cancellation"] is None
