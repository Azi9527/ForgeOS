from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from forgeos.codex_sdk import CodexTurnResult
from forgeos.execution import ForgeExecutionService
from forgeos.models import TaskStatus, TaskType, ValidationEvidence
from forgeos.service import ForgeService

NOW = "2026-08-24T00:00:00Z"


@dataclass
class FakeGateway:
    results: list[CodexTurnResult]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def run_turn(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        output_schema: dict | None = None,
    ) -> CodexTurnResult:
        assert output_schema is None
        self.calls.append((prompt, thread_id))
        return self.results.pop(0)


def result(
    *, thread_id: str = "thread-1", turn_id: str = "turn-1", status: str = "completed"
) -> CodexTurnResult:
    return CodexTurnResult(
        thread_id=thread_id,
        turn_id=turn_id,
        status=status,
        final_response="implemented",
        error_message=None,
        started_at=1,
        completed_at=2,
        duration_ms=1_000,
        items=(),
        usage={"totalTokens": 10},
    )


def task_service(tmp_path: Path) -> tuple[ForgeService, str]:
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    forge.init_project(name="Example")
    task = forge.create_task(
        title="SDK execution",
        task_type=TaskType.feature,
        objective="Execute through the SDK",
        acceptance_criteria=("turn persists",),
    )
    return forge, task.id


def test_run_records_thread_turn_and_requires_validation(tmp_path: Path) -> None:
    forge, task_id = task_service(tmp_path)
    gateway = FakeGateway([result()])

    task = ForgeExecutionService(forge, gateway).run_task(task_id)

    assert task.status is TaskStatus.validating
    assert task.codex_thread_id == "thread-1"
    assert task.last_turn_id == "turn-1"
    assert list((tmp_path / ".forge" / "executions" / task_id).glob("*.json"))
    assert forge.task(task_id) == task


def test_repair_resumes_same_codex_thread(tmp_path: Path) -> None:
    forge, task_id = task_service(tmp_path)
    gateway = FakeGateway([result(), result(turn_id="turn-2")])
    execution = ForgeExecutionService(forge, gateway)
    validating = execution.run_task(task_id)
    repairing = forge.apply_validation(
        task_id,
        evidence=ValidationEvidence(
            report_id="report-fail",
            passed=False,
            checked_at=NOW,
        ),
        expected_revision=validating.revision,
    )

    second = execution.run_task(repairing.id, prompt="Repair the failed check")

    assert second.status is TaskStatus.validating
    assert gateway.calls[0][1] is None
    assert gateway.calls[1][1] == "thread-1"
    assert second.last_turn_id == "turn-2"


def test_non_completed_turn_is_blocked_not_done(tmp_path: Path) -> None:
    forge, task_id = task_service(tmp_path)
    gateway = FakeGateway([result(status="interrupted")])

    task = ForgeExecutionService(forge, gateway).run_task(task_id)

    assert task.status is TaskStatus.blocked
    assert task.validation is None


def test_blocked_execution_can_retry_on_the_same_thread(tmp_path: Path) -> None:
    forge, task_id = task_service(tmp_path)
    gateway = FakeGateway(
        [
            result(status="interrupted"),
            result(turn_id="turn-2"),
        ]
    )
    execution = ForgeExecutionService(forge, gateway)
    blocked = execution.run_task(task_id)

    retried = execution.run_task(blocked.id, prompt="Retry after interruption")

    assert retried.status is TaskStatus.validating
    assert retried.last_turn_id == "turn-2"
    assert gateway.calls[1][1] == "thread-1"


def test_sdk_failure_blocks_task_and_is_audited(tmp_path: Path) -> None:
    forge, task_id = task_service(tmp_path)

    class BrokenGateway:
        def run_turn(self, prompt: str, **_kwargs: object) -> CodexTurnResult:
            raise RuntimeError("transport closed")

    with pytest.raises(RuntimeError, match="transport closed"):
        ForgeExecutionService(forge, BrokenGateway()).run_task(task_id)

    assert forge.task(task_id).status is TaskStatus.blocked
    assert "transport closed" in (tmp_path / ".forge" / "logs" / "audit.jsonl").read_text()
