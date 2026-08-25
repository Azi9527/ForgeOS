from __future__ import annotations

import json
from pathlib import Path

import pytest

from forgeos.cli import main


def invoke(workspace: Path, *arguments: str) -> int:
    return main(("--workspace", str(workspace), *arguments))


def test_cli_project_and_task_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert invoke(tmp_path, "init", "--name", "Example") == 0
    initialized = json.loads(capsys.readouterr().out)
    assert initialized["project"]["name"] == "Example"

    assert (
        invoke(
            tmp_path,
            "task",
            "new",
            "--title",
            "SDK integration",
            "--type",
            "FEATURE",
            "--objective",
            "Keep task authority outside Codex",
            "--acceptance",
            "task is persisted",
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["id"] == "FORGE-0001"

    assert invoke(tmp_path, "task", "show", "FORGE-0001") == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown == created

    assert invoke(tmp_path, "task", "list") == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed == {"tasks": [created]}

    assert invoke(tmp_path, "status") == 0
    status = json.loads(capsys.readouterr().out)
    assert status["task_count"] == 1
    assert status["tasks_by_status"] == {"CREATED": 1}


def test_cli_returns_nonzero_for_uninitialized_workspace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert invoke(tmp_path, "status") == 2
    assert "not initialized" in capsys.readouterr().err
