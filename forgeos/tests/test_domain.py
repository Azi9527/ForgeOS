from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from forgeos.config import ForgeConfig, ValidationCheckConfig
from forgeos.errors import ForgeConfigError, InvalidTransitionError
from forgeos.governance import (
    AcceptanceCriterionEvidence,
    CriterionStatus,
    ReviewChecklistItem,
    ReviewDimension,
    ReviewStatus,
)
from forgeos.models import (
    AcceptanceEvidence,
    ForgeProject,
    ForgeTask,
    ReviewEvidence,
    TaskStatus,
    TaskType,
    ValidationEvidence,
)
from forgeos.task_state import TaskStateMachine

NOW = "2026-08-24T00:00:00Z"


def project(tmp_path: Path) -> ForgeProject:
    return ForgeProject.create(name="Example", root=tmp_path, created_at=NOW)


def task() -> ForgeTask:
    return ForgeTask.create(
        task_id="FORGE-0001",
        title="Implement SDK integration",
        task_type=TaskType.feature,
        objective="Persist and resume Codex threads.",
        acceptance_criteria=("Thread ID survives restart",),
        created_at=NOW,
    )


def transition(actual: ForgeTask, target: TaskStatus) -> ForgeTask:
    return TaskStateMachine.transition(actual, target, changed_at=NOW, reason="test")


def test_project_and_config_round_trip(tmp_path: Path) -> None:
    config = ForgeConfig(
        project=project(tmp_path),
        validation_checks=(ValidationCheckConfig(name="tests", argv=("python", "-m", "pytest")),),
    )

    assert ForgeConfig.from_dict(config.to_dict()) == config


def test_config_rejects_future_schema(tmp_path: Path) -> None:
    value = ForgeConfig(project=project(tmp_path)).to_dict()
    value["schema_version"] = 99

    with pytest.raises(ForgeConfigError, match="unsupported ForgeConfig"):
        ForgeConfig.from_dict(value)


def test_task_round_trip() -> None:
    actual = task()

    assert ForgeTask.from_dict(actual.to_dict()) == actual


def test_task_requires_acceptance_criteria() -> None:
    with pytest.raises(ValueError, match="acceptance_criteria"):
        ForgeTask.create(
            task_id="FORGE-0001",
            title="No evidence",
            task_type=TaskType.fix,
            objective="Should fail",
            acceptance_criteria=(),
            created_at=NOW,
        )


def test_happy_path_requires_all_evidence() -> None:
    actual = task()
    for target in (
        TaskStatus.analyzing,
        TaskStatus.planned,
        TaskStatus.implementing,
        TaskStatus.validating,
    ):
        actual = transition(actual, target)

    with pytest.raises(InvalidTransitionError, match="validation evidence"):
        transition(actual, TaskStatus.reviewing)

    actual = replace(
        actual,
        validation=ValidationEvidence(
            report_id="vr-1",
            passed=True,
            checked_at=NOW,
            regression_report_id="rr-1",
        ),
    )
    actual = transition(actual, TaskStatus.reviewing)

    with pytest.raises(InvalidTransitionError, match="review evidence"):
        transition(actual, TaskStatus.accepting)

    actual = replace(
        actual,
        review=ReviewEvidence(
            approved=True,
            reviewer="human",
            reviewed_at=NOW,
            summary="Looks good",
            checklist=tuple(
                ReviewChecklistItem(dimension, ReviewStatus.passed, "verified")
                for dimension in ReviewDimension
            ),
        ),
    )
    actual = transition(actual, TaskStatus.accepting)

    with pytest.raises(InvalidTransitionError, match="acceptance evidence"):
        transition(actual, TaskStatus.done)

    actual = replace(
        actual,
        acceptance=AcceptanceEvidence(
            accepted_by="owner",
            accepted_at=NOW,
            note="Accepted",
            criteria=(
                AcceptanceCriterionEvidence(
                    criterion_id="AC-001",
                    criterion="Thread ID survives restart",
                    status=CriterionStatus.passed,
                    evidence="integration test passed",
                ),
            ),
        ),
        task_report_id="task-report-1",
    )
    actual = transition(actual, TaskStatus.done)

    assert actual.status is TaskStatus.done
    assert actual.revision == 7


def test_repair_loop() -> None:
    actual = task()
    for target in (
        TaskStatus.analyzing,
        TaskStatus.planned,
        TaskStatus.implementing,
        TaskStatus.validating,
        TaskStatus.repairing,
        TaskStatus.validating,
    ):
        actual = transition(actual, target)

    assert actual.status is TaskStatus.validating


def test_blocked_task_only_resumes_previous_state() -> None:
    actual = transition(task(), TaskStatus.analyzing)
    actual = transition(actual, TaskStatus.blocked)

    with pytest.raises(InvalidTransitionError, match="can only resume to ANALYZING"):
        transition(actual, TaskStatus.planned)

    resumed = transition(actual, TaskStatus.analyzing)
    assert resumed.status is TaskStatus.analyzing
    assert resumed.blocked_from is None


def test_terminal_state_cannot_transition() -> None:
    actual = transition(task(), TaskStatus.cancelled)

    with pytest.raises(InvalidTransitionError, match="terminal task"):
        transition(actual, TaskStatus.analyzing)
