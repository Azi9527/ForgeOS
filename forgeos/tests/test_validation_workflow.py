from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from forgeos.codex_sdk import CodexTurnResult
from forgeos.config import ValidationCheckConfig
from forgeos.errors import ForgeConflictError, ForgeValidationError
from forgeos.execution import ForgeExecutionService
from forgeos.governance import (
    AcceptanceCriterionEvidence,
    CriterionStatus,
    ReviewChecklistItem,
    ReviewDimension,
    ReviewStatus,
)
from forgeos.models import TaskStatus, TaskType
from forgeos.service import ForgeService
from forgeos.validation import OUTPUT_LIMIT, ValidationRunner
from forgeos.validation_types import ValidationLevel
from forgeos.workflow import ForgeWorkflowService

NOW = "2026-08-24T00:00:00Z"


def passing_checklist() -> tuple[ReviewChecklistItem, ...]:
    return tuple(
        ReviewChecklistItem(dimension, ReviewStatus.passed, "verified")
        for dimension in ReviewDimension
    )


def passing_criteria() -> tuple[AcceptanceCriterionEvidence, ...]:
    return (
        AcceptanceCriterionEvidence(
            criterion_id="AC-001",
            criterion="validation passes",
            status=CriterionStatus.passed,
            evidence="validation and regression reports passed",
        ),
    )


@dataclass
class FakeGateway:
    turn_index: int = 0

    def run_turn(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        output_schema: dict | None = None,
    ) -> CodexTurnResult:
        del prompt, output_schema
        self.turn_index += 1
        return CodexTurnResult(
            thread_id=thread_id or "thread-1",
            turn_id=f"turn-{self.turn_index}",
            status="completed",
            final_response="done",
            error_message=None,
            started_at=1,
            completed_at=2,
            duration_ms=1_000,
            items=(),
            usage=None,
        )


def workflow(
    tmp_path: Path,
    checks: tuple[ValidationCheckConfig, ...],
    *,
    repair_limit: int = 3,
) -> tuple[ForgeWorkflowService, str]:
    actual_checks = checks
    if checks and not any(check.level is ValidationLevel.build for check in checks):
        actual_checks = (
            ValidationCheckConfig(
                name="build",
                level=ValidationLevel.build,
                argv=(sys.executable, "-c", "pass"),
            ),
            *checks,
        )
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    forge.init_project(
        name="Example",
        validation_checks=actual_checks,
        repair_limit=repair_limit,
    )
    task = forge.create_task(
        title="Validated task",
        task_type=TaskType.feature,
        objective="Pass independent checks",
        acceptance_criteria=("validation passes",),
    )
    execution = ForgeExecutionService(forge, FakeGateway())
    runner = ValidationRunner(tmp_path, clock=lambda: NOW)
    return ForgeWorkflowService(forge, execution, runner), task.id


def test_full_pass_review_acceptance_flow(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="pass",
        argv=(sys.executable, "-c", "print('validation ok')"),
    )
    actual, task_id = workflow(tmp_path, (check,))

    result = actual.run_and_validate(task_id)
    restarted = ForgeService(tmp_path, clock=lambda: NOW)
    assert restarted.task(task_id) == result.task
    accepting = actual.review(
        task_id,
        approved=True,
        reviewer="maintainer",
        summary="Reviewed",
        checklist=passing_checklist(),
    )
    done = actual.accept(
        task_id,
        accepted_by="owner",
        note="Accepted",
        criteria=passing_criteria(),
    )

    assert result.validation_report is not None
    assert result.validation_report.passed is True
    assert result.task.status is TaskStatus.reviewing
    assert accepting.status is TaskStatus.accepting
    assert done.status is TaskStatus.done
    assert done.task_report_id is not None
    assert actual.task_reports.for_task(task_id)[-1].status == "DONE"
    assert (tmp_path / ".forge" / "tasks" / "completed" / f"{task_id}.json").is_file()


def test_failed_validation_enters_repair_and_resumes_thread(tmp_path: Path) -> None:
    marker = tmp_path / "pass-next"
    script = (
        "from pathlib import Path; import sys; "
        f"marker=Path({str(marker)!r}); "
        "sys.exit(0 if marker.exists() else 1)"
    )
    check = ValidationCheckConfig(name="conditional", argv=(sys.executable, "-c", script))
    actual, task_id = workflow(tmp_path, (check,))

    first = actual.run_and_validate(task_id)
    marker.write_text("ready", encoding="utf-8")
    second = actual.run_and_validate(task_id, prompt="Repair and retry")

    assert first.task.status is TaskStatus.repairing
    assert first.task.repair_attempts == 1
    assert second.task.status is TaskStatus.reviewing
    assert second.task.codex_thread_id == first.task.codex_thread_id
    assert second.task.last_turn_id == "turn-2"


def test_repair_limit_blocks_instead_of_looping(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="fail",
        argv=(sys.executable, "-c", "raise SystemExit(1)"),
    )
    actual, task_id = workflow(tmp_path, (check,), repair_limit=0)

    result = actual.run_and_validate(task_id)

    assert result.task.status is TaskStatus.blocked
    assert result.task.blocked_from is TaskStatus.validating


def test_no_validation_checks_fail_closed(tmp_path: Path) -> None:
    actual, task_id = workflow(tmp_path, ())

    with pytest.raises(ForgeValidationError, match="at least one"):
        actual.run_and_validate(task_id)

    assert actual.forge.task(task_id).status is TaskStatus.created


def test_timeout_is_failed_evidence(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="timeout",
        argv=(sys.executable, "-c", "import time; time.sleep(2)"),
        timeout_seconds=1,
    )
    runner = ValidationRunner(tmp_path, clock=lambda: NOW)

    report = runner.run("FORGE-0001", (check,))

    assert report.passed is False
    assert report.checks[0].timed_out is True
    assert report.checks[0].exit_code is None


def test_validation_output_is_bounded(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="large-output",
        argv=(sys.executable, "-c", f"print('x' * {OUTPUT_LIMIT + 100})"),
    )
    runner = ValidationRunner(tmp_path, clock=lambda: NOW)

    report = runner.run("FORGE-0001", (check,))

    assert report.passed is True
    assert report.checks[0].stdout.endswith("[TRUNCATED BY FORGEOS]")
    assert len(report.checks[0].stdout) < OUTPUT_LIMIT + 100


def test_validation_does_not_interpret_shell_metacharacters(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    suspicious_argument = f"; echo compromised > {marker}"
    check = ValidationCheckConfig(
        name="literal-argument",
        argv=(
            sys.executable,
            "-c",
            "import sys; print(sys.argv[1])",
            suspicious_argument,
        ),
    )

    report = ValidationRunner(tmp_path, clock=lambda: NOW).run("FORGE-0001", (check,))

    assert report.passed is True
    assert suspicious_argument in report.checks[0].stdout
    assert marker.exists() is False


@pytest.mark.parametrize("authority", ["agent", "Codex", "MODEL"])
def test_agent_identity_cannot_review_or_accept(tmp_path: Path, authority: str) -> None:
    check = ValidationCheckConfig(name="pass", argv=(sys.executable, "-c", "pass"))
    actual, task_id = workflow(tmp_path, (check,))
    actual.run_and_validate(task_id)

    with pytest.raises(ForgeConflictError, match="coding agents"):
        actual.review(
            task_id,
            approved=True,
            reviewer=authority,
            summary="self approved",
            checklist=passing_checklist(),
        )

    actual.review(
        task_id,
        approved=True,
        reviewer="maintainer",
        summary="approved",
        checklist=passing_checklist(),
    )
    with pytest.raises(ForgeConflictError, match="coding agents"):
        actual.accept(
            task_id,
            accepted_by=authority,
            note="self accepted",
            criteria=passing_criteria(),
        )
    assert actual.task_reports.for_task(task_id) == ()
