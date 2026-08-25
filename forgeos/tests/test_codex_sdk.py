from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from forgeos import ApprovalPolicy, CodexSdkGateway, CodexSdkSettings, WorkspaceAccess
from forgeos.model_input import ModelInput, ModelTextItem


class Status(str, Enum):
    completed = "completed"


@dataclass
class FakeError:
    message: str


class FakeModel:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def model_dump(self, *, mode: str, by_alias: bool) -> dict[str, Any]:
        assert mode == "json"
        assert by_alias is True
        return dict(self.value)


@dataclass
class FakeResult:
    id: str = "turn-1"
    status: Status = Status.completed
    error: FakeError | None = None
    started_at: int | None = 10
    completed_at: int | None = 12
    duration_ms: int | None = 2_000
    final_response: str | None = "done"
    items: tuple[Any, ...] = (FakeModel({"type": "agentMessage"}),)
    usage: Any = FakeModel({"totalTokens": 42})


class FakeThread:
    def __init__(self, thread_id: str) -> None:
        self.id = thread_id
        self.runs: list[tuple[str, dict[str, Any]]] = []

    def run(self, input: str, **kwargs: Any) -> FakeResult:
        self.runs.append((input, kwargs))
        return FakeResult()


@dataclass
class FakeItem:
    text: str
    phase: str = "finalAnswer"
    type: str = "agentMessage"

    def model_dump(self, *, mode: str, by_alias: bool) -> dict[str, Any]:
        assert mode == "json"
        assert by_alias is True
        return {"type": self.type, "phase": self.phase, "text": self.text}


@dataclass
class FakeTurn:
    id: str = "turn-controlled"
    status: Status = Status.completed
    error: FakeError | None = None
    started_at: int | None = 20
    completed_at: int | None = 22
    duration_ms: int | None = 2_000


@dataclass
class FakeNotification:
    method: str
    payload: Any


class FakeHandle:
    id = "turn-controlled"

    def __init__(self) -> None:
        self.interrupts = 0
        self.steers: list[str] = []

    def stream(self) -> Any:
        item = FakeItem("controlled done")
        yield FakeNotification(
            "item/completed",
            SimpleNamespace(turn_id=self.id, item=item),
        )
        yield FakeNotification(
            "thread/tokenUsage/updated",
            SimpleNamespace(turn_id=self.id, token_usage=FakeModel({"totalTokens": 8})),
        )
        yield FakeNotification("turn/completed", SimpleNamespace(turn=FakeTurn()))

    def interrupt(self) -> dict[str, Any]:
        self.interrupts += 1
        return {"interrupted": True}

    def steer(self, input: str) -> dict[str, Any]:
        self.steers.append(input)
        return {"steered": True}


class ControlledFakeThread(FakeThread):
    def __init__(self, thread_id: str) -> None:
        super().__init__(thread_id)
        self.handle = FakeHandle()

    def turn(self, input: str, **kwargs: Any) -> FakeHandle:
        self.runs.append((input, kwargs))
        return self.handle


class FakeClient:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []
        self.resumed: list[tuple[str, dict[str, Any]]] = []
        self.threads: list[FakeThread] = []
        self.close_count = 0

    def thread_start(self, **kwargs: Any) -> FakeThread:
        self.started.append(kwargs)
        thread = FakeThread("thread-new")
        self.threads.append(thread)
        return thread

    def thread_resume(self, thread_id: str, **kwargs: Any) -> FakeThread:
        self.resumed.append((thread_id, kwargs))
        thread = FakeThread(thread_id)
        self.threads.append(thread)
        return thread

    def close(self) -> None:
        self.close_count += 1


class ControlledFakeClient(FakeClient):
    def thread_start(self, **kwargs: Any) -> ControlledFakeThread:
        self.started.append(kwargs)
        thread = ControlledFakeThread("thread-controlled")
        self.threads.append(thread)
        return thread

    def thread_resume(self, thread_id: str, **kwargs: Any) -> ControlledFakeThread:
        self.resumed.append((thread_id, kwargs))
        thread = ControlledFakeThread(thread_id)
        self.threads.append(thread)
        return thread


class FailingResumeClient(ControlledFakeClient):
    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def thread_resume(self, thread_id: str, **kwargs: Any) -> ControlledFakeThread:
        self.resumed.append((thread_id, kwargs))
        raise RuntimeError(self.message)


def settings(tmp_path: Path) -> CodexSdkSettings:
    return CodexSdkSettings(workspace=tmp_path)


def test_starts_new_thread_and_normalizes_runtime_evidence(tmp_path: Path) -> None:
    client = FakeClient()

    with CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client) as gateway:
        result = gateway.run_turn(
            "Implement feature X",
            output_schema={"type": "object"},
        )

    assert result.thread_id == "thread-new"
    assert result.turn_id == "turn-1"
    assert result.status == "completed"
    assert result.final_response == "done"
    assert result.items == ({"type": "agentMessage"},)
    assert result.usage == {"totalTokens": 42}
    assert client.started == [
        {
            "cwd": str(tmp_path.resolve()),
            "ephemeral": False,
        }
    ]
    assert client.threads[0].runs == [
        ("Implement feature X", {"output_schema": {"type": "object"}})
    ]
    assert client.close_count == 1


def test_resumes_persisted_thread(tmp_path: Path) -> None:
    client = FakeClient()
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    result = gateway.run_turn("Continue", thread_id="thread-existing")
    gateway.close()

    assert result.thread_id == "thread-existing"
    assert client.started == []
    assert client.resumed == [("thread-existing", {"cwd": str(tmp_path.resolve())})]
    assert client.close_count == 1


def test_gateway_reuses_one_sdk_client(tmp_path: Path) -> None:
    client = FakeClient()
    factory_calls = 0

    def factory(_settings: CodexSdkSettings) -> FakeClient:
        nonlocal factory_calls
        factory_calls += 1
        return client

    with CodexSdkGateway(settings(tmp_path), client_factory=factory) as gateway:
        first = gateway.run_turn("First")
        gateway.run_turn("Second", thread_id=first.thread_id)

    assert factory_calls == 1
    assert len(client.threads) == 2


def test_controlled_turn_streams_progress_and_exposes_control(tmp_path: Path) -> None:
    client = ControlledFakeClient()
    progress: list[dict[str, Any]] = []
    controls: list[Any] = []
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    result = gateway.run_turn_controlled(
        "Implement with progress",
        developer_instructions="Bounded Forge context",
        on_progress=lambda event: progress.append(event.to_dict()),
        on_started=controls.append,
    )
    interrupt = controls[0].interrupt()
    repeated = controls[0].interrupt()

    assert result.thread_id == "thread-controlled"
    assert result.turn_id == "turn-controlled"
    assert result.status == "completed"
    assert result.final_response == "controlled done"
    assert result.usage == {"totalTokens": 8}
    assert [event["method"] for event in progress] == [
        "item/completed",
        "thread/tokenUsage/updated",
        "turn/completed",
    ]
    assert client.started[0]["developer_instructions"] == "Bounded Forge context"
    assert interrupt == {"interrupted": True}
    assert repeated == {"already_requested": True}
    assert client.threads[0].handle.interrupts == 1


def test_controlled_resume_injects_fresh_context_in_turn_not_thread_options(
    tmp_path: Path,
) -> None:
    client = ControlledFakeClient()
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    gateway.run_turn_controlled(
        "Fresh bounded runtime context",
        thread_id="thread-existing",
        developer_instructions="must not become a resume override",
    )

    assert client.resumed == [("thread-existing", {"cwd": str(tmp_path.resolve())})]
    assert client.threads[0].runs == [("Fresh bounded runtime context", {})]


def test_missing_rollout_starts_replacement_thread_with_fresh_context(tmp_path: Path) -> None:
    client = FailingResumeClient(
        "JSON-RPC error -32600: no rollout found for thread id thread-missing"
    )
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    result = gateway.run_turn_controlled(
        "Recover safely",
        thread_id="thread-missing",
        developer_instructions="Bounded replacement context",
        allow_missing_rollout_replacement=True,
    )

    assert result.thread_id == "thread-controlled"
    assert client.resumed == [("thread-missing", {"cwd": str(tmp_path.resolve())})]
    assert client.started == [
        {
            "cwd": str(tmp_path.resolve()),
            "developer_instructions": "Bounded replacement context",
            "ephemeral": False,
        }
    ]
    assert client.threads[0].runs == [("Recover safely", {})]


def test_missing_rollout_replacement_is_denied_by_default(tmp_path: Path) -> None:
    client = FailingResumeClient(
        "JSON-RPC error -32600: no rollout found for thread id thread-missing"
    )
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    with pytest.raises(RuntimeError, match="no rollout found"):
        gateway.run_turn_controlled("Continue", thread_id="thread-missing")

    assert client.started == []


def test_resume_error_other_than_missing_rollout_is_not_masked(tmp_path: Path) -> None:
    client = FailingResumeClient("JSON-RPC error -32600: invalid resume request")
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    with pytest.raises(RuntimeError, match="invalid resume request"):
        gateway.run_turn_controlled("Continue", thread_id="thread-existing")

    assert client.started == []


def test_sdk_boundary_bounds_direct_model_input(tmp_path: Path) -> None:
    client = FakeClient()
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    gateway.run_turn("中" * 10_000)

    prompt, _options = client.threads[0].runs[0]
    assert len(prompt.encode("utf-8")) <= 900
    assert "[TRUNCATED BY FORGEOS]" in prompt


def test_controlled_boundary_bounds_prompt_and_developer_instructions(tmp_path: Path) -> None:
    client = ControlledFakeClient()
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: client)

    gateway.run_turn_controlled(
        "中" * 10_000,
        developer_instructions="d" * 10_000,
    )

    prompt, _options = client.threads[0].runs[0]
    instructions = client.started[0]["developer_instructions"]
    assert len(prompt.encode("utf-8")) <= 900
    assert len(instructions.encode("utf-8")) <= 900
    assert "[TRUNCATED BY FORGEOS]" in prompt
    assert "[TRUNCATED BY FORGEOS]" in instructions


@pytest.mark.parametrize("value", ["", "   "])
def test_rejects_empty_prompt(tmp_path: Path, value: str) -> None:
    gateway = CodexSdkGateway(settings(tmp_path), client_factory=lambda _settings: FakeClient())

    with pytest.raises(ValueError, match="prompt must not be empty"):
        gateway.run_turn(value)


def test_settings_use_safe_defaults(tmp_path: Path) -> None:
    actual = settings(tmp_path)

    assert actual.workspace_access is WorkspaceAccess.workspace_write
    assert actual.approval_policy is ApprovalPolicy.deny_all
    assert actual.ephemeral_threads is False


def test_settings_reject_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workspace must be an existing directory"):
        CodexSdkSettings(workspace=tmp_path / "missing")


def test_official_client_receives_forgeos_security_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    raw_client = FakeClient()
    captured_config: dict[str, Any] = {}

    class FakeCodexConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured_config.update(kwargs)

    @dataclass
    class FakeTextInput:
        text: str

    fake_module = SimpleNamespace(
        ApprovalMode=SimpleNamespace(deny_all="sdk-deny", auto_review="sdk-review"),
        Codex=lambda _config: raw_client,
        CodexConfig=FakeCodexConfig,
        Sandbox=SimpleNamespace(read_only="sdk-read", workspace_write="sdk-write"),
        TextInput=FakeTextInput,
    )
    monkeypatch.setitem(__import__("sys").modules, "openai_codex", fake_module)

    with CodexSdkGateway(settings(tmp_path)) as gateway:
        gateway.run_turn(ModelInput((ModelTextItem.create("task", "Inspect the repository"),)))

    assert captured_config["cwd"] == str(tmp_path.resolve())
    assert captured_config["experimental_api"] is False
    assert raw_client.started == [
        {
            "cwd": str(tmp_path),
            "ephemeral": False,
            "approval_mode": "sdk-deny",
            "sandbox": "sdk-write",
        }
    ]
    assert raw_client.threads[0].runs == [([FakeTextInput("Inspect the repository")], {})]
    assert raw_client.close_count == 1
