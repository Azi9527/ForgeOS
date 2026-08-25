from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from forgeos.codex_sdk import CodexTurnResult
from forgeos.control import ForgeControlService
from forgeos.web_server import ForgeWebServer

NOW = "2026-08-24T00:00:00Z"


@dataclass
class FakeGateway:
    def run_turn(
        self,
        prompt: str,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> CodexTurnResult:
        del prompt, output_schema
        return CodexTurnResult(
            thread_id=thread_id or "thread-web",
            turn_id="turn-web",
            status="completed",
            final_response="Web API turn completed",
            error_message=None,
            started_at=1,
            completed_at=2,
            duration_ms=1_000,
            items=(),
            usage=None,
        )


@contextmanager
def running_server(tmp_path: Path) -> Iterator[tuple[ForgeControlService, ForgeWebServer]]:
    control = ForgeControlService(
        tmp_path,
        gateway_factory=FakeGateway,
        clock=lambda: NOW,
    )
    server = ForgeWebServer(control, port=0, token="test-token")
    server.start()
    try:
        yield control, server
    finally:
        server.close()
        control.close()


def request(
    server: ForgeWebServer,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    token: str | None = "test-token",
) -> tuple[int, dict[str, Any] | str, dict[str, str]]:
    data = None if payload is None else json.dumps(payload).encode()
    headers = {}
    if token is not None:
        headers["X-ForgeOS-Token"] = token
    if data is not None:
        headers["Content-Type"] = "application/json"
    actual = Request(
        f"http://127.0.0.1:{server.port}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        response = urlopen(actual, timeout=5)
    except HTTPError as exc:
        response = exc
    raw = response.read().decode()
    content_type = response.headers.get("Content-Type", "")
    body: dict[str, Any] | str = json.loads(raw) if "application/json" in content_type else raw
    return response.status, body, dict(response.headers.items())


def test_web_ui_requires_token_and_serves_security_headers(tmp_path: Path) -> None:
    with running_server(tmp_path) as (_control, server):
        forbidden, body, _headers = request(server, "/", token=None)
        ok, html, headers = request(server, "/?token=test-token", token=None)
        asset_status, script, _asset_headers = request(server, "/assets/app.js", token=None)
        operator_status, operator_script, _operator_headers = request(
            server, "/assets/operator.js", token=None
        )

    assert forbidden == 403
    assert body["error"]["code"] == "forbidden"
    assert ok == 200
    assert 'meta name="forge-token" content="test-token"' in html
    assert headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert headers["X-Frame-Options"] == "DENY"
    assert asset_status == 200
    assert operator_status == 200
    assert "async function refresh()" in script
    assert 'activeJob.kind === "run" ? "Codex 运行中…"' in script
    assert 'button.textContent = "正在提交…"' in script
    assert 'button.textContent = "正在审核…"' in script
    assert "window.prompt" not in script
    assert "decision-dialog" in html
    assert 'data-action="interrupt"' in script
    assert "Review Checklist" in script
    assert "L5 Acceptance Criteria" in script
    assert "Forge Task Report" in script
    assert "submitSteer" in script
    assert "const form = event.currentTarget" in script
    assert "form.reset()" in script
    assert "N5 RELEASE & OPERATOR" in html
    assert "operator-dialog" in html
    assert "runReleaseCheck" in operator_script
    assert "decideMemoryFromOperator" in operator_script
    assert "retirePolicyFromOperator" in operator_script
    assert "window.prompt" not in operator_script


def test_web_api_full_project_task_flow(tmp_path: Path) -> None:
    with running_server(tmp_path) as (control, server):
        unauthorized, error, _headers = request(server, "/api/status", token=None)
        initialized, project, _headers = request(
            server,
            "/api/project/init",
            method="POST",
            payload={
                "name": "Web Project",
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
            },
        )
        created_status, task, _headers = request(
            server,
            "/api/tasks",
            method="POST",
            payload={
                "title": "Clickable task",
                "task_type": "FEATURE",
                "objective": "Drive ForgeOS from a browser",
                "acceptance_criteria": ["validation passes"],
            },
        )
        run_status, job, _headers = request(
            server,
            f"/api/tasks/{task['id']}/run",
            method="POST",
            payload={},
        )
        completed = control.jobs.wait(job["id"])
        detail_status, detail, _headers = request(server, f"/api/tasks/{task['id']}")
        review_status, reviewed, _headers = request(
            server,
            f"/api/tasks/{task['id']}/review",
            method="POST",
            payload={
                "approved": True,
                "reviewer": "maintainer",
                "summary": "approved",
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
        accept_status, accepted, _headers = request(
            server,
            f"/api/tasks/{task['id']}/accept",
            method="POST",
            payload={
                "accepted_by": "owner",
                "note": "accepted",
                "criteria": [
                    {
                        "criterion_id": "AC-001",
                        "criterion": "validation passes",
                        "status": "PASS",
                        "evidence": "browser workflow passed",
                    }
                ],
            },
        )
        report_status, report, _headers = request(
            server,
            f"/api/tasks/{task['id']}/report",
        )

    assert unauthorized == 403
    assert error["error"]["code"] == "forbidden"
    assert initialized == 201
    assert project["project"]["name"] == "Web Project"
    assert created_status == 201
    assert run_status == 202
    assert completed.state.value == "SUCCEEDED"
    assert detail_status == 200
    assert detail["task"]["status"] == "REVIEWING"
    assert detail["executions"][0]["thread_id"] == "thread-web"
    assert review_status == 200
    assert reviewed["status"] == "ACCEPTING"
    assert accept_status == 200
    assert accepted["status"] == "DONE"
    assert accepted["task_report_id"] is not None
    assert report_status == 200
    assert report["report_id"] == accepted["task_report_id"]
    assert report["regression_result"]["passed"] is True


def test_web_api_memory_lifecycle_and_policy_evidence(tmp_path: Path) -> None:
    with running_server(tmp_path) as (_control, server):
        request(
            server,
            "/api/project/init",
            method="POST",
            payload={"name": "N3 Web", "validation_checks": []},
        )
        _status, task, _headers = request(
            server,
            "/api/tasks",
            method="POST",
            payload={
                "title": "N3 API",
                "task_type": "FEATURE",
                "objective": "Show policy evidence",
                "acceptance_criteria": ["visible"],
            },
        )
        created_status, memory, _headers = request(
            server,
            "/api/memories",
            method="POST",
            payload={
                "kind": "PATTERN",
                "title": "API pattern",
                "body": "Use a human acceptance gate",
                "created_by": "maintainer",
                "source_task_id": task["id"],
            },
        )
        accepted_status, accepted, _headers = request(
            server,
            f"/api/memories/{memory['id']}/accept",
            method="POST",
            payload={
                "decided_by": "maintainer",
                "reason": "reviewed",
                "expected_revision": 0,
            },
        )
        list_status, listed, _headers = request(server, "/api/memories?status=ACCEPTED")
        policy_status, policy, _headers = request(
            server,
            f"/api/tasks/{task['id']}/policy-check",
            method="POST",
            payload={},
        )

    assert created_status == 201
    assert accepted_status == 200
    assert accepted["status"] == "ACCEPTED"
    assert list_status == 200
    assert listed["memories"] == [accepted]
    assert policy_status == 200
    assert policy["passed"] is True


def test_web_api_n4_operations_and_cancellation(tmp_path: Path) -> None:
    with running_server(tmp_path) as (_control, server):
        request(
            server,
            "/api/project/init",
            method="POST",
            payload={
                "name": "N4 Web",
                "validation_checks": [],
                "execution_attempt_limit": 5,
            },
        )
        _status, task, _headers = request(
            server,
            "/api/tasks",
            method="POST",
            payload={
                "title": "N4 operations",
                "task_type": "FIX",
                "objective": "Verify operational controls",
                "acceptance_criteria": ["operations are visible"],
            },
        )
        operations_status, operations, _headers = request(server, "/api/operations")
        integrity_status, integrity, _headers = request(
            server,
            "/api/operations/integrity-scan",
            method="POST",
            payload={},
        )
        migration_status, migration, _headers = request(server, "/api/migration")
        cancel_status, cancellation, _headers = request(
            server,
            f"/api/tasks/{task['id']}/cancel",
            method="POST",
            payload={"requested_by": "owner", "reason": "cancel from Web API"},
        )
        detail_status, detail, _headers = request(server, f"/api/tasks/{task['id']}")

    assert operations_status == 200
    assert operations["migration"]["required"] is False
    assert integrity_status == 200
    assert integrity["passed"] is True
    assert migration_status == 200
    assert migration["to_version"] == 1
    assert cancel_status == 202
    assert cancellation["task"]["status"] == "CANCELLED"
    assert detail_status == 200
    assert detail["cancellation"]["status"] == "APPLIED"
    assert detail["integrity"]["id"] == integrity["id"]


def test_web_api_n5_release_audit_memory_and_policy_operator(tmp_path: Path) -> None:
    with running_server(tmp_path) as (_control, server):
        request(
            server,
            "/api/project/init",
            method="POST",
            payload={"name": "N5 Web", "validation_checks": []},
        )
        release_status, release, _headers = request(
            server,
            "/api/release/check",
            method="POST",
            payload={},
        )
        policy_status, policy, _headers = request(
            server,
            "/api/policies",
            method="POST",
            payload={
                "id": "project.web-deny",
                "name": "Web deny",
                "target": "TASK_PATH",
                "patterns": ["private/**"],
                "reason": "operator rule",
                "created_by": "maintainer",
            },
        )
        listed_status, listed, _headers = request(server, "/api/policies")
        audit_status, audit, _headers = request(
            server,
            "/api/audit?event_type=policy.created&limit=10",
        )
        retired_status, retired, _headers = request(
            server,
            f"/api/policies/{policy['id']}/retire",
            method="POST",
            payload={"retired_by": "maintainer", "reason": "superseded"},
        )
        operator_status, operator, _headers = request(server, "/api/operator")

    assert release_status == 200
    assert release["passed"] is True
    assert policy_status == 201
    assert policy["active"] is True
    assert listed_status == 200
    assert any(item["id"] == policy["id"] for item in listed["policies"])
    assert audit_status == 200
    assert audit["matched"] == 1
    assert retired_status == 200
    assert retired["active"] is False
    assert operator_status == 200
    assert operator["package_version"] == "0.2.0"
    assert operator["fixtures"]["passed"] is True


def test_web_server_rejects_non_loopback_binding(tmp_path: Path) -> None:
    control = ForgeControlService(tmp_path, gateway_factory=FakeGateway, clock=lambda: NOW)
    try:
        with pytest.raises(ValueError, match="loopback"):
            ForgeWebServer(control, host="0.0.0.0")
    finally:
        control.close()


def test_web_api_exposes_doctor_and_rejects_control_without_active_turn(tmp_path: Path) -> None:
    with running_server(tmp_path) as (_control, server):
        request(
            server,
            "/api/project/init",
            method="POST",
            payload={"name": "Control", "validation_checks": []},
        )
        _status, task, _headers = request(
            server,
            "/api/tasks",
            method="POST",
            payload={
                "title": "Control",
                "task_type": "FEATURE",
                "objective": "Control one turn",
                "acceptance_criteria": ["controlled"],
            },
        )
        doctor_status, doctor, _headers = request(server, "/api/doctor")
        interrupt_status, interrupt, _headers = request(
            server,
            f"/api/tasks/{task['id']}/interrupt",
            method="POST",
            payload={},
        )

    assert doctor_status == 200
    assert doctor["passed"] is True
    assert interrupt_status == 409
    assert interrupt["error"]["code"] == "conflict"
