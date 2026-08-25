from dataclasses import replace
from pathlib import Path

import pytest

from forgeos.errors import ForgeConflictError
from forgeos.execution_records import (
    AttemptState,
    ExecutionAttemptRepository,
    ExecutionStepResult,
    StepState,
)
from forgeos.service import ForgeService


def repository(tmp_path: Path) -> ExecutionAttemptRepository:
    service = ForgeService(tmp_path, clock=lambda: "2026-08-24T00:00:00Z")
    service.init_project(name="Attempts")
    return ExecutionAttemptRepository(service.store)


def test_attempt_round_trip_steps_and_terminal_state(tmp_path: Path) -> None:
    actual = repository(tmp_path)
    attempt = actual.create(
        task_id="FORGE-0001",
        kind="run",
        created_at="2026-08-24T00:00:00Z",
    )
    attempt = actual.start(attempt, started_at="2026-08-24T00:00:01Z")
    attempt = actual.attach_turn(attempt, thread_id="thread-1", turn_id="turn-1")
    step = ExecutionStepResult(
        name="codex_turn",
        status=StepState.completed,
        started_at="2026-08-24T00:00:01Z",
        finished_at="2026-08-24T00:00:02Z",
        input_summary={"prompt_sha256": "abc"},
        output_summary={"status": "completed"},
        files_changed=("src/app.py",),
        commands=(("python", "-m", "pytest"),),
    )
    attempt = actual.append_step(attempt, step)
    attempt = actual.finish(
        attempt,
        status=AttemptState.completed,
        finished_at="2026-08-24T00:00:02Z",
    )

    assert actual.load(attempt.task_id, attempt.id) == attempt
    assert actual.list_for_task(attempt.task_id) == (attempt,)


def test_attempt_revision_conflict_does_not_overwrite(tmp_path: Path) -> None:
    actual = repository(tmp_path)
    queued = actual.create(
        task_id="FORGE-0001",
        kind="run",
        created_at="2026-08-24T00:00:00Z",
    )
    started = actual.start(queued, started_at="2026-08-24T00:00:01Z")
    stale = replace(queued, status=AttemptState.failed, revision=1)

    with pytest.raises(ForgeConflictError, match="revision changed"):
        actual.save(stale, expected_revision=0)

    assert actual.load(started.task_id, started.id) == started


def test_recovery_marks_only_incomplete_attempts_interrupted(tmp_path: Path) -> None:
    actual = repository(tmp_path)
    running = actual.create(
        task_id="FORGE-0001",
        kind="run",
        created_at="2026-08-24T00:00:00Z",
    )
    running = actual.start(running, started_at="2026-08-24T00:00:01Z")
    completed = actual.create(
        task_id="FORGE-0002",
        kind="run",
        created_at="2026-08-24T00:00:00Z",
    )
    completed = actual.start(completed, started_at="2026-08-24T00:00:01Z")
    completed = actual.finish(
        completed,
        status=AttemptState.completed,
        finished_at="2026-08-24T00:00:02Z",
    )

    recovered = actual.recover_incomplete(recovered_at="2026-08-24T00:01:00Z")

    assert len(recovered) == 1
    assert recovered[0].status is AttemptState.interrupted
    assert actual.load(completed.task_id, completed.id) == completed


def test_attempt_rejects_unsafe_identifiers_and_unbounded_step_data(tmp_path: Path) -> None:
    actual = repository(tmp_path)

    with pytest.raises(ValueError, match="unsafe"):
        actual.create(task_id="../escape", kind="run", created_at="now")
    with pytest.raises(ValueError, match="16384 bytes"):
        ExecutionStepResult(
            name="context",
            status=StepState.completed,
            started_at="now",
            output_summary={"value": "x" * 17_000},
        )
