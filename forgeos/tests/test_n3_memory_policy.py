import sys
from pathlib import Path

import pytest

from forgeos.cli import main
from forgeos.config import ValidationCheckConfig
from forgeos.context import ContextAuthority, ContextPackageBuilder
from forgeos.control import ForgeControlService
from forgeos.errors import ForgeConfigError, ForgeConflictError, ForgePolicyError
from forgeos.git_evidence import GitSnapshot
from forgeos.memory import MemoryKind, MemoryService, MemoryStatus
from forgeos.models import TaskType
from forgeos.policy import PolicyEngine
from forgeos.service import ForgeService
from forgeos.validation_types import ValidationLevel

NOW = "2026-08-24T00:00:00Z"


def initialized(tmp_path: Path) -> ForgeService:
    service = ForgeService(tmp_path, clock=lambda: NOW)
    service.init_project(name="N3")
    return service


def task(service: ForgeService, *, modules: tuple[str, ...] = ()):
    return service.create_task(
        title="Adopt retry pattern",
        task_type=TaskType.feature,
        objective="Use the established retry pattern in the payment module",
        acceptance_criteria=("retry is bounded",),
        related_modules=modules,
    )


def git_snapshot(project: Path, task_id: str) -> GitSnapshot:
    return GitSnapshot(
        id="git-n3-baseline",
        task_id=task_id,
        kind="baseline",
        captured_at=NOW,
        available=True,
        repository_root=str(project),
        head="a" * 40,
        branch="main",
        detached=False,
        dirty=False,
        changed_files=(),
        status_sha256="b" * 64,
        diff_sha256="c" * 64,
    )


def test_memory_requires_human_acceptance_and_revision_evidence(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    memory = MemoryService(service.store, clock=lambda: NOW)
    draft = memory.create(
        kind=MemoryKind.decision,
        title="Bound retries",
        body="Use no more than three attempts.",
        created_by="codex-agent",
        tags=("retry",),
    )

    with pytest.raises(ForgeConflictError, match="cannot decide"):
        memory.decide(
            draft.id,
            accepted=True,
            decided_by="codex-agent",
            reason="self approval",
            expected_revision=0,
        )
    with pytest.raises(ForgeConflictError, match="cannot decide"):
        memory.decide(
            draft.id,
            accepted=True,
            decided_by="forgeos-system",
            reason="automatic approval",
            expected_revision=0,
        )

    accepted = memory.decide(
        draft.id,
        accepted=True,
        decided_by="maintainer",
        reason="reviewed against incident evidence",
        expected_revision=0,
    )

    assert accepted.status is MemoryStatus.accepted
    assert accepted.revision == 1
    assert MemoryService(service.store, clock=lambda: NOW).get(draft.id) == accepted
    with pytest.raises(ForgeConflictError, match="revision changed"):
        memory.decide(
            draft.id,
            accepted=False,
            decided_by="maintainer",
            reason="stale update",
            expected_revision=0,
        )


def test_retrieval_is_accepted_only_stable_bounded_and_redacted(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    current_task = task(service, modules=("payments/retry.py",))
    memory = MemoryService(service.store, clock=lambda: NOW)
    accepted = memory.create(
        kind=MemoryKind.pattern,
        title="Payment retry pattern",
        body="Retry three times; token=do-not-inject",
        created_by="maintainer",
        tags=("payment", "retry"),
        related_modules=("payments/retry.py",),
    )
    accepted = memory.decide(
        accepted.id,
        accepted=True,
        decided_by="maintainer",
        reason="production pattern",
        expected_revision=0,
    )
    memory.create(
        kind=MemoryKind.failure,
        title="Payment retry draft",
        body="Unreviewed retry advice",
        created_by="forgeos-system",
        tags=("payment", "retry"),
    )

    first, records = memory.select_for_task(current_task, persist=False)
    second, repeated = memory.select_for_task(current_task, persist=False)
    package = ContextPackageBuilder(service.store, clock=lambda: NOW).build(
        current_task, git_snapshot(tmp_path, current_task.id)
    )

    assert first == second
    assert records == repeated == (accepted,)
    assert first.total_bytes <= 16_384
    assert len(first.items) <= 8
    fragments = [item for item in package.fragments if item.kind == "memory"]
    assert len(fragments) == 1
    assert fragments[0].authority is ContextAuthority.runtime_data
    assert "do-not-inject" not in fragments[0].content
    assert "[REDACTED]" in fragments[0].content
    assert package.memory_selection_id is not None


def test_memory_supersede_keeps_both_records_and_provenance(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    memory = MemoryService(service.store, clock=lambda: NOW)
    records = []
    for title in ("Old decision", "New decision"):
        draft = memory.create(
            kind=MemoryKind.decision,
            title=title,
            body=f"Evidence for {title}",
            created_by="maintainer",
        )
        records.append(
            memory.decide(
                draft.id,
                accepted=True,
                decided_by="maintainer",
                reason="reviewed",
                expected_revision=0,
            )
        )

    old = memory.supersede(
        records[0].id,
        replacement_id=records[1].id,
        decided_by="maintainer",
        reason="newer architecture decision",
        expected_revision=1,
    )

    assert old.status is MemoryStatus.superseded
    assert old.superseded_by == records[1].id
    assert memory.get(records[1].id).status is MemoryStatus.accepted


def test_policy_denies_protected_paths_and_destructive_validation(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    engine = PolicyEngine(service.store, clock=lambda: NOW)
    protected = task(service, modules=(".git/config",))
    safe_check = ValidationCheckConfig(
        name="tests",
        level=ValidationLevel.unit,
        argv=(sys.executable, "-m", "pytest"),
    )

    with pytest.raises(ForgePolicyError, match="protect-git-metadata"):
        engine.enforce_task(protected, (safe_check,))

    ordinary_git_module = task(service, modules=("git/config.py",))
    assert engine.enforce_task(ordinary_git_module, (safe_check,)).passed is True

    safe = task(service, modules=("payments",))
    destructive = ValidationCheckConfig(
        name="cleanup",
        level=ValidationLevel.unit,
        argv=("git", "reset", "--hard"),
    )
    with pytest.raises(ForgePolicyError, match="validation-nondestructive"):
        engine.enforce_task(safe, (destructive,))

    evaluations = engine.evaluations(safe.id)
    assert evaluations[-1]["passed"] is False
    assert evaluations[-1]["violations"][0]["target"] == "VALIDATION_COMMAND"


def test_policy_files_are_additive_deny_and_invalid_allow_fails_closed(tmp_path: Path) -> None:
    service = initialized(tmp_path)
    current_task = task(service, modules=("production/database",))
    service.store.write_record(
        "policies/no-production.json",
        {
            "schema_version": 1,
            "id": "project.no-production",
            "name": "No production changes",
            "effect": "DENY",
            "target": "TASK_PATH",
            "patterns": ["production/**"],
            "reason": "production access needs a separate approved workflow",
        },
    )
    engine = PolicyEngine(service.store, clock=lambda: NOW)

    with pytest.raises(ForgePolicyError, match="project.no-production"):
        engine.enforce_task(current_task, ())

    service.store.write_record(
        "policies/unsafe-allow.json",
        {
            "schema_version": 1,
            "id": "project.allow-all",
            "name": "Unsafe override",
            "effect": "ALLOW",
            "target": "TASK_PATH",
            "patterns": ["**"],
            "reason": "attempt to weaken built-ins",
        },
    )
    with pytest.raises(ForgeConfigError, match="only support additive DENY"):
        engine.enforce_task(current_task, ())


def test_control_exposes_memory_and_policy_evidence(tmp_path: Path) -> None:
    control = ForgeControlService(tmp_path, clock=lambda: NOW)
    try:
        control.initialize({"name": "N3 Control", "validation_checks": []})
        created = control.create_task(
            {
                "title": "Memory API",
                "task_type": "FEATURE",
                "objective": "Expose memory evidence",
                "acceptance_criteria": ["evidence is visible"],
            }
        )
        draft = control.create_memory(
            {
                "kind": "PATTERN",
                "title": "Control pattern",
                "body": "Expose evidence explicitly",
                "created_by": "maintainer",
                "tags": ["control"],
                "source_task_id": created["id"],
            }
        )
        accepted = control.decide_memory(
            draft["id"],
            {
                "decided_by": "maintainer",
                "reason": "verified",
                "expected_revision": 0,
            },
            accepted=True,
        )
        policy = control.policy_check(created["id"])
        detail = control.task_detail(created["id"])

        assert accepted["status"] == "ACCEPTED"
        assert control.list_memories("ACCEPTED")["memories"] == [accepted]
        assert policy["passed"] is True
        assert detail["memories"] == [accepted]
        assert detail["policy_evaluations"][-1]["id"] == policy["id"]
    finally:
        control.close()


def test_cli_memory_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(("--workspace", str(tmp_path), "init", "--name", "N3 CLI")) == 0
    capsys.readouterr()
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "memory",
                "new",
                "--kind",
                "DECISION",
                "--title",
                "Use file memory",
                "--body",
                "Keep accepted records in Git",
                "--created-by",
                "maintainer",
            )
        )
        == 0
    )
    draft = __import__("json").loads(capsys.readouterr().out)
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "memory",
                "accept",
                draft["id"],
                "--decided-by",
                "maintainer",
                "--reason",
                "reviewed",
                "--revision",
                "0",
            )
        )
        == 0
    )
    assert __import__("json").loads(capsys.readouterr().out)["status"] == "ACCEPTED"
