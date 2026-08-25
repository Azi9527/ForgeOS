import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from forgeos.cli import main
from forgeos.codex_sdk import CodexTurnResult
from forgeos.config import ForgeConfig, ValidationCheckConfig
from forgeos.errors import ForgeConflictError
from forgeos.execution import ForgeExecutionService
from forgeos.governance import (
    AcceptanceEvidence,
    ReviewChecklistItem,
    ReviewDimension,
    ReviewEvidence,
    ReviewStatus,
    validate_acceptance_evidence,
    validate_review_evidence,
)
from forgeos.memory import MemoryKind, MemoryService, MemoryStatus
from forgeos.models import ForgeProject, TaskStatus, TaskType
from forgeos.regression import (
    RegressionClassification,
    RegressionService,
    ValidationReportRepository,
)
from forgeos.service import ForgeService
from forgeos.validation import ValidationRunner
from forgeos.validation_types import ValidationLevel, ValidationPurpose
from forgeos.workflow import ForgeWorkflowService

NOW = "2026-08-24T00:00:00Z"


@dataclass
class RepairingGateway:
    marker: Path
    turns: int = 0

    def run_turn(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        output_schema: dict | None = None,
    ) -> CodexTurnResult:
        del prompt, output_schema
        self.turns += 1
        if self.turns == 1:
            self.marker.write_text("regression", encoding="utf-8")
        else:
            self.marker.unlink()
        return CodexTurnResult(
            thread_id=thread_id or "thread-n2",
            turn_id=f"turn-{self.turns}",
            status="completed",
            final_response="implemented" if self.turns == 1 else "repaired",
            error_message=None,
            started_at=1,
            completed_at=2,
            duration_ms=1,
            items=(),
            usage=None,
        )


def checklist(status: ReviewStatus = ReviewStatus.passed) -> tuple[ReviewChecklistItem, ...]:
    return tuple(
        ReviewChecklistItem(dimension, status, "verified") for dimension in ReviewDimension
    )


def test_validation_config_and_report_are_typed_and_round_trip(tmp_path: Path) -> None:
    check = ValidationCheckConfig(
        name="build",
        level=ValidationLevel.build,
        argv=(sys.executable, "-c", "pass"),
    )
    config = ForgeConfig(
        project=ForgeProject.create(name="N2", root=tmp_path, created_at=NOW),
        validation_checks=(check,),
    )
    report = ValidationRunner(tmp_path, clock=lambda: NOW).run(
        "FORGE-0001",
        (check,),
        purpose=ValidationPurpose.baseline,
    )

    assert ForgeConfig.from_dict(config.to_dict()) == config
    assert report.purpose is ValidationPurpose.baseline
    assert report.checks[0].level is ValidationLevel.build
    assert report.levels[0].level is ValidationLevel.build
    assert type(report).from_dict(report.to_dict()) == report


def test_regression_distinguishes_new_and_preexisting_failures(tmp_path: Path) -> None:
    marker = tmp_path / "broken"
    script = (
        "from pathlib import Path; import sys; "
        f"sys.exit(1 if Path({str(marker)!r}).exists() else 0)"
    )
    check = ValidationCheckConfig(
        name="unit",
        level=ValidationLevel.unit,
        argv=(sys.executable, "-c", script),
    )
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    forge.init_project(name="N2", validation_checks=(check,))
    runner = ValidationRunner(tmp_path, clock=lambda: NOW)
    baseline = runner.run("FORGE-0001", (check,), purpose=ValidationPurpose.baseline)
    ValidationReportRepository(forge.store).save(baseline)
    marker.write_text("broken", encoding="utf-8")
    current = runner.run("FORGE-0001", (check,))

    regression = RegressionService(forge.store, clock=lambda: NOW).compare(baseline, current)

    assert regression.passed is False
    assert regression.checks[0].classification is RegressionClassification.new_regression

    failing_baseline = runner.run(
        "FORGE-0002",
        (check,),
        purpose=ValidationPurpose.baseline,
    )
    still_failing = runner.run("FORGE-0002", (check,))
    existing = RegressionService(forge.store, clock=lambda: NOW).compare(
        failing_baseline,
        still_failing,
    )
    assert existing.passed is True
    assert existing.checks[0].classification is RegressionClassification.pre_existing_failure


def test_structured_governance_fails_closed() -> None:
    incomplete = ReviewEvidence(
        approved=True,
        reviewer="maintainer",
        reviewed_at=NOW,
        summary="incomplete",
        checklist=checklist()[:-1],
    )
    with pytest.raises(ForgeConflictError, match="every required dimension"):
        validate_review_evidence(incomplete)

    acceptance = AcceptanceEvidence(
        accepted_by="owner",
        accepted_at=NOW,
        note="missing criterion",
        criteria=(),
    )
    with pytest.raises(ForgeConflictError, match="every declared criterion"):
        validate_acceptance_evidence(("works",), acceptance)


def test_complete_regression_repair_review_accept_report_flow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = tmp_path / "regression"
    script = (
        "from pathlib import Path; import sys; "
        f"sys.exit(1 if Path({str(marker)!r}).exists() else 0)"
    )
    check = ValidationCheckConfig(
        name="unit",
        level=ValidationLevel.unit,
        argv=(sys.executable, "-c", script),
    )
    forge = ForgeService(tmp_path, clock=lambda: NOW)
    forge.init_project(
        name="N2 E2E",
        validation_checks=(
            ValidationCheckConfig(
                name="build",
                level=ValidationLevel.build,
                argv=(sys.executable, "-c", "pass"),
            ),
            check,
        ),
    )
    task = forge.create_task(
        title="Repair a regression",
        task_type=TaskType.fix,
        objective="Demonstrate the complete N2 lifecycle",
        acceptance_criteria=("regression is repaired",),
    )
    workflow = ForgeWorkflowService(
        forge,
        ForgeExecutionService(forge, RepairingGateway(marker)),
        ValidationRunner(tmp_path, clock=lambda: NOW),
    )

    failed = workflow.run_and_validate(task.id)
    repaired = workflow.run_and_validate(task.id, prompt="repair the regression")
    review_arguments = [
        item
        for dimension in ReviewDimension
        for item in ("--check", f"{dimension.value}=PASS:verified")
    ]
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "review",
                task.id,
                "--reviewer",
                "maintainer",
                "--approved",
                "--summary",
                "all dimensions verified",
                "--risk-note",
                "low residual risk",
                "--technical-debt",
                "none identified",
                *review_arguments,
            )
        )
        == 0
    )
    accepting = json.loads(capsys.readouterr().out)
    assert (
        main(
            (
                "--workspace",
                str(tmp_path),
                "accept",
                task.id,
                "--accepted-by",
                "owner",
                "--note",
                "accepted from evidence",
                "--criterion",
                "PASS:current unit check and L4 comparison passed",
            )
        )
        == 0
    )
    done_payload = json.loads(capsys.readouterr().out)
    done = forge.task(task.id)
    assert main(("--workspace", str(tmp_path), "task", "report", task.id)) == 0
    cli_report = json.loads(capsys.readouterr().out)

    assert failed.task.status is TaskStatus.repairing
    assert failed.regression_report is not None
    assert failed.regression_report.passed is False
    assert repaired.task.status is TaskStatus.reviewing
    assert repaired.regression_report is not None
    assert repaired.regression_report.passed is True
    assert accepting["status"] == TaskStatus.accepting.value
    assert done_payload["status"] == TaskStatus.done.value
    assert done.status is TaskStatus.done
    assert done.task_report_id is not None
    report = workflow.task_reports.for_task(task.id)[-1]
    assert report.report_id == done.task_report_id
    assert report.repair_attempts == 1
    assert report.regression_result["passed"] is True
    assert report.acceptance["criteria"][0]["status"] == "PASS"
    assert cli_report == report.to_dict()

    restarted = ForgeService(tmp_path, clock=lambda: NOW)
    assert restarted.task(task.id) == done
    generated_memory = MemoryService(restarted.store, clock=lambda: NOW).list()
    assert {item.kind for item in generated_memory} == {MemoryKind.failure, MemoryKind.task}
    assert all(item.status is MemoryStatus.draft for item in generated_memory)
    assert all(item.source_task_id == task.id for item in generated_memory)
