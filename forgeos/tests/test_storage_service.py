from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import forgeos.storage as storage_module
from forgeos.audit import AuditActor
from forgeos.config import ForgeConfig, ValidationCheckConfig
from forgeos.errors import ForgeConfigError, ForgeConflictError
from forgeos.models import ForgeProject, TaskStatus, TaskType
from forgeos.service import ForgeService
from forgeos.storage import ForgeStore

NOW = "2026-08-24T00:00:00Z"


def service(tmp_path: Path) -> ForgeService:
    return ForgeService(tmp_path, clock=lambda: NOW)


def initialized_service(tmp_path: Path) -> ForgeService:
    actual = service(tmp_path)
    actual.init_project(
        name="Example",
        validation_checks=(
            ValidationCheckConfig(name="compile", argv=("python", "-m", "compileall")),
        ),
    )
    return actual


def test_init_is_idempotent_and_creates_protocol_layout(tmp_path: Path) -> None:
    actual = service(tmp_path)

    first = actual.init_project(name="Example")
    second = actual.init_project(name="Example")

    assert second == first
    assert json.loads((tmp_path / ".forge" / "forge.yaml").read_text(encoding="utf-8"))
    assert (tmp_path / ".forge" / "tasks" / "active").is_dir()
    assert (tmp_path / ".forge" / "validation" / "results").is_dir()
    assert [event.event_type for event in actual.audit.read_all()] == ["project.initialized"]


def test_init_does_not_overwrite_conflicting_project(tmp_path: Path) -> None:
    actual = service(tmp_path)
    actual.init_project(name="Example")

    with pytest.raises(ForgeConflictError, match="already initialized"):
        actual.init_project(name="Different")


def test_create_and_reload_tasks_with_monotonic_ids(tmp_path: Path) -> None:
    actual = initialized_service(tmp_path)

    first = actual.create_task(
        title="First",
        task_type=TaskType.feature,
        objective="First objective",
        acceptance_criteria=("passes",),
    )
    second = actual.create_task(
        title="Second",
        task_type=TaskType.fix,
        objective="Second objective",
        acceptance_criteria=("fixed",),
    )

    restarted = service(tmp_path)
    assert first.id == "FORGE-0001"
    assert second.id == "FORGE-0002"
    assert restarted.task(first.id) == first
    assert restarted.tasks() == (first, second)


def test_task_id_allocation_is_concurrent_safe(tmp_path: Path) -> None:
    actual = initialized_service(tmp_path)
    store = actual.store

    with ThreadPoolExecutor(max_workers=8) as executor:
        identifiers = tuple(executor.map(lambda _index: store.allocate_task_id("FORGE"), range(20)))

    assert len(set(identifiers)) == 20
    assert set(identifiers) == {f"FORGE-{index:04d}" for index in range(1, 21)}


def test_windows_existing_lock_permission_error_is_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = initialized_service(tmp_path).store
    lock_path = store.forge_dir / "tasks" / ".permission.lock"
    real_open = storage_module.os.open
    attempts = 0

    def permission_once(path: Path, flags: int) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            path.write_text("held", encoding="utf-8")
            raise PermissionError(13, "lock exists", str(path))
        return real_open(path, flags)

    def release_lock(_seconds: float) -> None:
        lock_path.unlink(missing_ok=True)

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(storage_module.os, "open", permission_once)
    monkeypatch.setattr(storage_module.time, "sleep", release_lock)

    with store.exclusive_lock(lock_path):
        assert lock_path.is_file()

    assert attempts == 2
    assert lock_path.exists() is False


def test_transition_rejects_stale_revision(tmp_path: Path) -> None:
    actual = initialized_service(tmp_path)
    task = actual.create_task(
        title="Revision",
        task_type=TaskType.test,
        objective="Check revisions",
        acceptance_criteria=("stale write rejected",),
    )
    actual.transition_task(
        task.id,
        TaskStatus.analyzing,
        expected_revision=task.revision,
        reason="start",
        actor=AuditActor.system,
    )

    with pytest.raises(ForgeConflictError, match="revision changed"):
        actual.transition_task(
            task.id,
            TaskStatus.analyzing,
            expected_revision=task.revision,
            reason="stale",
            actor=AuditActor.system,
        )


def test_audit_redacts_nested_secrets(tmp_path: Path) -> None:
    actual = initialized_service(tmp_path)

    event = actual.audit.append(
        "security.test",
        actor=AuditActor.system,
        payload={
            "api_key": "top-secret",
            "nested": {"authorization": "Bearer secret", "safe": "visible"},
        },
    )

    assert event.payload == {
        "api_key": "[REDACTED]",
        "nested": {"authorization": "[REDACTED]", "safe": "visible"},
    }
    assert "top-secret" not in (tmp_path / ".forge" / "logs" / "audit.jsonl").read_text()


def test_store_rejects_path_traversal(tmp_path: Path) -> None:
    actual = initialized_service(tmp_path)

    with pytest.raises(ForgeConfigError, match="unsafe Forge relative path"):
        actual.store.write_record("../outside.json", {"bad": True})


def test_reopening_legacy_layout_adds_only_missing_protocol_directories(tmp_path: Path) -> None:
    initialized_service(tmp_path)
    additions = (
        tmp_path / ".forge" / "execution-attempts",
        tmp_path / ".forge" / "evidence" / "git",
        tmp_path / ".forge" / "context" / "packages",
    )
    for directory in additions:
        directory.rmdir()

    reopened = ForgeService(tmp_path)

    assert all(directory.is_dir() for directory in additions)
    assert reopened.config().project.name == "Example"


def test_store_rejects_symlinked_forge_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge_link = tmp_path / ".forge"
    forge_link.mkdir()
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == forge_link or original_is_symlink(path),
    )

    store = ForgeStore(tmp_path)
    config = ForgeConfig(project=ForgeProject.create(name="Example", root=tmp_path, created_at=NOW))
    with pytest.raises(ForgeConfigError, match="must not be a symbolic link"):
        store.initialize(config)
