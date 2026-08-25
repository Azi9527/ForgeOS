from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from forgeos.codex_sdk import CodexTurnResult
from forgeos.control import ForgeControlService, JobState
from forgeos.errors import ForgeConflictError
from forgeos.execution_events import CodexProgressEvent, CodexTurnControl
from forgeos.execution_records import AttemptState
from forgeos.model_input import ModelInput
from forgeos.models import TaskStatus

NOW = "2026-08-24T00:00:00Z"


@dataclass
class FakeGateway:
    turns: int = 0
    close_count: int = 0

    def run_turn(
        self,
        prompt: ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> CodexTurnResult:
        del prompt, output_schema
        self.turns += 1
        return CodexTurnResult(
            thread_id=thread_id or "thread-control",
            turn_id=f"turn-{self.turns}",
            status="completed",
            final_response="Implemented from the control API",
            error_message=None,
            started_at=1,
            completed_at=2,
            duration_ms=1_000,
            items=(),
            usage=None,
        )

    def close(self) -> None:
        self.close_count += 1


@dataclass
class BlockingGateway(FakeGateway):
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def run_turn(
        self,
        prompt: ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> CodexTurnResult:
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("test gateway was not released")
        return super().run_turn(prompt, thread_id=thread_id, output_schema=output_schema)


@dataclass
class FakeActiveControl:
    release: threading.Event
    thread_id: str = "thread-controlled"
    turn_id: str = "turn-controlled"
    id: str = "turn-controlled"
    steers: list[str] = field(default_factory=list)
    interrupt_count: int = 0

    def steer(self, input: str) -> dict[str, Any]:
        self.steers.append(input)
        return {"steered": True}

    def interrupt(self) -> dict[str, Any]:
        self.interrupt_count += 1
        self.release.set()
        return {"interrupted": True}


@dataclass
class ControlledBlockingGateway(FakeGateway):
    started: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    control: FakeActiveControl = field(init=False)

    def __post_init__(self) -> None:
        self.control = FakeActiveControl(self.release)

    def run_turn_controlled(
        self,
        prompt: ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
        developer_instructions: str | None = None,
        allow_missing_rollout_replacement: bool = False,
        on_progress: Any = None,
        on_started: Any = None,
    ) -> CodexTurnResult:
        del thread_id, output_schema, allow_missing_rollout_replacement
        assert "ForgeOS runtime evidence follows" in "\n".join(prompt.texts())
        assert developer_instructions is None
        on_started(CodexTurnControl(thread_id=self.control.thread_id, handle=self.control))
        on_progress(CodexProgressEvent(1, "turn/started", {"phase": "started"}))
        self.started.set()
        if not self.release.wait(5):
            raise TimeoutError("controlled test gateway was not released")
        return CodexTurnResult(
            thread_id=self.control.thread_id,
            turn_id=self.control.turn_id,
            status="interrupted",
            final_response=None,
            error_message=None,
            started_at=1,
            completed_at=2,
            duration_ms=1_000,
            items=(),
            usage=None,
        )


def initialized_control(tmp_path: Path, gateway: FakeGateway) -> ForgeControlService:
    control = ForgeControlService(
        tmp_path,
        gateway_factory=lambda: gateway,
        clock=lambda: NOW,
    )
    control.initialize(
        {
            "name": "Control Project",
            "validation_checks": [
                {
                    "name": "build",
                    "level": "L1_BUILD",
                    "argv": [sys.executable, "-c", "pass"],
                },
                {
                    "name": "pass",
                    "level": "L2_UNIT",
                    "argv": [sys.executable, "-c", "print('ok')"],
                },
            ],
        }
    )
    return control


def create_task(control: ForgeControlService) -> dict[str, Any]:
    return control.create_task(
        {
            "title": "Control surface",
            "task_type": "FEATURE",
            "objective": "Expose ForgeOS safely",
            "acceptance_criteria": ["validation passes", "human accepts"],
        }
    )


def test_control_full_background_workflow_and_evidence(tmp_path: Path) -> None:
    gateway = FakeGateway()
    control = initialized_control(tmp_path, gateway)
    try:
        task = create_task(control)
        submitted = control.submit_run(task["id"], {})
        completed = control.jobs.wait(submitted["id"])

        assert completed.state is JobState.succeeded
        assert completed.result["task"]["status"] == "REVIEWING"
        detail = control.task_detail(task["id"])
        assert detail["task"]["codex_thread_id"] == "thread-control"
        assert detail["executions"][0]["final_response"] == "Implemented from the control API"
        assert detail["validations"][0]["passed"] is True
        assert detail["jobs"][0]["state"] == "SUCCEEDED"

        reviewed = control.review(
            task["id"],
            {
                "approved": True,
                "reviewer": "maintainer",
                "summary": "looks good",
                "checklist": [
                    {"dimension": dimension, "status": "PASS", "note": "verified"}
                    for dimension in (
                        "ARCHITECTURE",
                        "CODE_QUALITY",
                        "RISK",
                        "TESTS",
                        "BACKWARD_COMPATIBILITY",
                        "TECHNICAL_DEBT",
                    )
                ],
            },
        )
        accepted = control.accept(
            task["id"],
            {
                "accepted_by": "owner",
                "note": "accepted from UI",
                "criteria": [
                    {
                        "criterion_id": "AC-001",
                        "criterion": "validation passes",
                        "status": "PASS",
                        "evidence": "validation and regression reports passed",
                    },
                    {
                        "criterion_id": "AC-002",
                        "criterion": "human accepts",
                        "status": "PASS",
                        "evidence": "owner reviewed the evidence",
                    },
                ],
            },
        )

        assert reviewed["status"] == "ACCEPTING"
        assert accepted["status"] == "DONE"
        assert accepted["task_report_id"] is not None
        assert gateway.close_count == 1
        assert any(event["event_type"] == "control.job.queued" for event in detail["audit"])
    finally:
        control.close()


def test_control_rejects_parallel_jobs_for_one_task(tmp_path: Path) -> None:
    gateway = BlockingGateway()
    control = initialized_control(tmp_path, gateway)
    try:
        task = create_task(control)
        first = control.submit_run(task["id"], {})
        assert gateway.started.wait(2)

        with pytest.raises(ForgeConflictError, match="active control job"):
            control.submit_run(task["id"], {})

        gateway.release.set()
        assert control.jobs.wait(first["id"]).state is JobState.succeeded
    finally:
        gateway.release.set()
        control.close()


def test_control_stream_progress_steer_interrupt_and_persist_recovery(
    tmp_path: Path,
) -> None:
    gateway = ControlledBlockingGateway()
    control = initialized_control(tmp_path, gateway)
    try:
        task = create_task(control)
        submitted = control.submit_run(task["id"], {})
        assert gateway.started.wait(2)

        active = control.jobs.get(submitted["id"])
        steer = control.steer(task["id"], {"input": "Preserve compatibility"})
        interrupted = control.interrupt(task["id"])
        completed = control.jobs.wait(submitted["id"])
        detail = control.task_detail(task["id"])

        assert active.progress["event"]["summary"] == {"phase": "started"}
        assert steer["runtime"] == {"steered": True}
        assert gateway.control.steers == ["Preserve compatibility"]
        assert interrupted["attempt"]["status"] == "INTERRUPTING"
        assert completed.error_message is None, completed.to_dict()
        assert completed.state is JobState.succeeded
        assert completed.result["task"]["status"] == "BLOCKED"
        assert detail["attempts"][-1]["status"] == AttemptState.interrupted.value
        assert any(
            event["event_type"] == "codex.turn.interrupt_requested" for event in detail["audit"]
        )
    finally:
        gateway.release.set()
        control.close()


def test_control_rejects_oversized_steer_before_sdk_call(tmp_path: Path) -> None:
    gateway = ControlledBlockingGateway()
    control = initialized_control(tmp_path, gateway)
    try:
        task = create_task(control)
        submitted = control.submit_run(task["id"], {})
        assert gateway.started.wait(2)

        with pytest.raises(ValueError, match="steer input exceeds 900 bytes"):
            control.steer(task["id"], {"input": "中" * 301})

        assert gateway.control.steers == []
        control.interrupt(task["id"])
        assert control.jobs.wait(submitted["id"]).state is JobState.succeeded
    finally:
        gateway.release.set()
        control.close()


def test_control_validation_retry_resumes_blocked_gate(tmp_path: Path) -> None:
    marker = tmp_path / "validation-ready"
    script = (
        "from pathlib import Path; import sys; "
        f"sys.exit(0 if Path({str(marker)!r}).exists() else 1)"
    )
    gateway = FakeGateway()
    control = ForgeControlService(
        tmp_path,
        gateway_factory=lambda: gateway,
        clock=lambda: NOW,
    )
    control.initialize(
        {
            "name": "Retry Project",
            "repair_limit": 0,
            "validation_checks": [{"name": "conditional", "argv": [sys.executable, "-c", script]}],
        }
    )
    try:
        task = create_task(control)
        first = control.jobs.wait(control.submit_run(task["id"], {})["id"])
        assert first.result["task"]["status"] == "BLOCKED"
        assert first.result["task"]["blocked_from"] == "VALIDATING"

        marker.write_text("ready", encoding="utf-8")
        retried = control.jobs.wait(control.submit_validation(task["id"])["id"])

        assert retried.state is JobState.succeeded
        assert retried.result["task"]["status"] == "REVIEWING"
        assert control.forge.task(task["id"]).status is TaskStatus.reviewing
    finally:
        control.close()


def test_control_reports_uninitialized_workspace_and_validates_input(tmp_path: Path) -> None:
    control = ForgeControlService(tmp_path, gateway_factory=FakeGateway, clock=lambda: NOW)
    try:
        assert control.status() == {"initialized": False, "workspace": str(tmp_path.resolve())}
        with pytest.raises(ValueError, match="validation_checks"):
            control.initialize({"name": "Invalid", "validation_checks": "pytest"})
    finally:
        control.close()


def test_control_diagnostics_are_bounded_and_exclude_runtime_credentials(tmp_path: Path) -> None:
    gateway = FakeGateway()
    control = ForgeControlService(
        tmp_path,
        gateway_factory=lambda: gateway,
        clock=lambda: NOW,
    )
    try:
        control.initialize({"name": "Diagnostics", "validation_checks": []})
        actual = control.diagnostic_bundle()
    finally:
        control.close()

    assert actual["schema_version"] == 1
    assert actual["generated_at"] == NOW
    assert actual["status"]["project"]["name"] == "Diagnostics"
    assert actual["doctor"]["workspace"] == str(tmp_path.resolve())
    assert actual["recent_jobs"] == []
    assert "token" not in str(actual).lower()


def test_task_detail_orders_chronological_evidence(tmp_path: Path) -> None:
    control = initialized_control(tmp_path, FakeGateway())
    try:
        task = create_task(control)
        control.forge.store.write_record(
            f"executions/{task['id']}/z-older.json",
            {"turn_id": "turn-older", "started_at": 10, "final_response": "older"},
        )
        control.forge.store.write_record(
            f"executions/{task['id']}/a-newer.json",
            {"turn_id": "turn-newer", "started_at": 20, "final_response": "newer"},
        )
        control.forge.store.write_record(
            "validation/results/z-older.json",
            {
                "task_id": task["id"],
                "report_id": "validation-older",
                "started_at": "2026-08-24T00:00:01Z",
                "passed": True,
            },
        )
        control.forge.store.write_record(
            "validation/results/a-newer.json",
            {
                "task_id": task["id"],
                "report_id": "validation-newer",
                "started_at": "2026-08-24T00:00:02Z",
                "passed": True,
            },
        )

        detail = control.task_detail(task["id"])

        assert [item["final_response"] for item in detail["executions"]] == ["older", "newer"]
        assert [item["report_id"] for item in detail["validations"]] == [
            "validation-older",
            "validation-newer",
        ]
    finally:
        control.close()
