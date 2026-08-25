"""Safe, narrow integration with the official OpenAI Codex Python SDK."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from .execution_events import CodexProgressEvent, CodexTurnControl, SdkTurnHandle
from .model_input import MODEL_ITEM_BYTE_LIMIT, ModelInput, bounded_model_text


class WorkspaceAccess(str, Enum):
    """Filesystem access ForgeOS may grant to a Codex thread."""

    read_only = "read_only"
    workspace_write = "workspace_write"


class ApprovalPolicy(str, Enum):
    """High-level handling for requests that exceed the current sandbox."""

    deny_all = "deny_all"
    auto_review = "auto_review"


@dataclass(frozen=True, slots=True)
class CodexSdkSettings:
    """Configuration owned by ForgeOS for one Codex SDK connection."""

    workspace: Path
    codex_bin: Path | None = None
    model: str | None = None
    developer_instructions: str | None = None
    workspace_access: WorkspaceAccess = WorkspaceAccess.workspace_write
    approval_policy: ApprovalPolicy = ApprovalPolicy.deny_all
    ephemeral_threads: bool = False
    config_overrides: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        workspace = self.workspace.resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace must be an existing directory: {workspace}")
        object.__setattr__(self, "workspace", workspace)

        if self.codex_bin is not None:
            codex_bin = self.codex_bin.resolve()
            if not codex_bin.is_file():
                raise ValueError(f"codex_bin must be an existing file: {codex_bin}")
            object.__setattr__(self, "codex_bin", codex_bin)


@dataclass(frozen=True, slots=True)
class CodexTurnResult:
    """Runtime evidence returned by Codex; it is not Forge task acceptance."""

    thread_id: str
    turn_id: str
    status: str
    final_response: str | None
    error_message: str | None
    started_at: int | None
    completed_at: int | None
    duration_ms: int | None
    items: tuple[dict[str, Any], ...]
    usage: dict[str, Any] | None
    replaced_thread_id: str | None = None


class CodexSdkIntegrationError(RuntimeError):
    """Base exception raised by the ForgeOS Codex SDK boundary."""


class CodexSdkUnavailableError(CodexSdkIntegrationError):
    """Raised when the official Python SDK is not installed."""


class _SdkThread(Protocol):
    id: str

    def run(self, input: Any, **kwargs: Any) -> Any: ...

    def turn(self, input: Any, **kwargs: Any) -> SdkTurnHandle: ...


class _SdkClient(Protocol):
    def thread_start(self, **kwargs: Any) -> _SdkThread: ...

    def thread_resume(self, thread_id: str, **kwargs: Any) -> _SdkThread: ...

    def close(self) -> None: ...


ClientFactory = Callable[[CodexSdkSettings], _SdkClient]
ProgressCallback = Callable[[CodexProgressEvent], None]
TurnStartedCallback = Callable[[CodexTurnControl], None]


class _OfficialClientAdapter:
    """Bind ForgeOS security defaults to every SDK thread lifecycle call."""

    def __init__(
        self,
        client: Any,
        *,
        approval_mode: Any,
        sandbox: Any,
        text_input_type: Any,
    ) -> None:
        self._client = client
        self._approval_mode = approval_mode
        self._sandbox = sandbox
        self._text_input_type = text_input_type

    def prepare_input(self, input: str | ModelInput) -> Any:
        if isinstance(input, ModelInput):
            return [self._text_input_type(text=item.text) for item in input.items]
        return input

    def thread_start(self, **kwargs: Any) -> _SdkThread:
        return self._client.thread_start(
            **kwargs,
            approval_mode=self._approval_mode,
            sandbox=self._sandbox,
        )

    def thread_resume(self, thread_id: str, **kwargs: Any) -> _SdkThread:
        return self._client.thread_resume(
            thread_id,
            **kwargs,
            approval_mode=self._approval_mode,
            sandbox=self._sandbox,
        )

    def close(self) -> None:
        self._client.close()


class CodexSdkGateway:
    """Own a Codex SDK connection and run new or resumed thread turns."""

    def __init__(
        self,
        settings: CodexSdkSettings,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or _create_official_client
        self._client: _SdkClient | None = None

    def __enter__(self) -> CodexSdkGateway:
        self.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def start(self) -> None:
        """Start one reusable SDK connection."""

        if self._client is None:
            self._client = self._client_factory(self.settings)

    def close(self) -> None:
        """Close the SDK connection if it is running."""

        if self._client is None:
            return
        client = self._client
        self._client = None
        client.close()

    def run_turn(
        self,
        prompt: str | ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
        allow_missing_rollout_replacement: bool = False,
    ) -> CodexTurnResult:
        """Run one turn on a new thread or resume a persisted Codex thread."""

        _validate_prompt(prompt)
        if thread_id is not None and not thread_id.strip():
            raise ValueError("thread_id must not be empty")

        self.start()
        client = self._require_client()
        thread_options = _thread_options(self.settings)
        if thread_id is None:
            thread = client.thread_start(
                **thread_options,
                ephemeral=self.settings.ephemeral_threads,
            )
            replaced_thread_id = None
        else:
            thread, replaced_thread_id = _resume_or_restart(
                client,
                thread_id,
                resume_options=thread_options,
                start_options=thread_options,
                ephemeral=self.settings.ephemeral_threads,
                allow_replacement=allow_missing_rollout_replacement,
            )

        run_options: dict[str, Any] = {}
        if output_schema is not None:
            run_options["output_schema"] = output_schema
        result = thread.run(_prepare_prompt(client, prompt), **run_options)
        return _normalize_turn_result(
            thread.id,
            result,
            replaced_thread_id=replaced_thread_id,
        )

    def run_turn_controlled(
        self,
        prompt: str | ModelInput,
        *,
        thread_id: str | None = None,
        output_schema: dict[str, Any] | None = None,
        developer_instructions: str | None = None,
        allow_missing_rollout_replacement: bool = False,
        on_progress: ProgressCallback | None = None,
        on_started: TurnStartedCallback | None = None,
    ) -> CodexTurnResult:
        """Run through the public TurnHandle API for progress and control."""

        _validate_prompt(prompt)
        if thread_id is not None and not thread_id.strip():
            raise ValueError("thread_id must not be empty")

        self.start()
        client = self._require_client()
        thread_options = _thread_options(
            self.settings,
            developer_instructions=developer_instructions,
        )
        if thread_id is None:
            thread = client.thread_start(
                **thread_options,
                ephemeral=self.settings.ephemeral_threads,
            )
            replaced_thread_id = None
        else:
            thread, replaced_thread_id = _resume_or_restart(
                client,
                thread_id,
                resume_options={"cwd": str(self.settings.workspace)},
                start_options=thread_options,
                ephemeral=self.settings.ephemeral_threads,
                allow_replacement=allow_missing_rollout_replacement,
            )

        run_options: dict[str, Any] = {}
        if output_schema is not None:
            run_options["output_schema"] = output_schema
        handle = thread.turn(_prepare_prompt(client, prompt), **run_options)
        control = CodexTurnControl(
            thread_id=thread.id,
            handle=handle,
            replaced_thread_id=replaced_thread_id,
        )
        if on_started is not None:
            on_started(control)
        return _collect_controlled_result(
            thread.id,
            control.turn_id,
            handle,
            on_progress=on_progress,
            replaced_thread_id=replaced_thread_id,
        )

    def _require_client(self) -> _SdkClient:
        if self._client is None:
            raise CodexSdkIntegrationError("Codex SDK connection is not running")
        return self._client


def _resume_or_restart(
    client: _SdkClient,
    thread_id: str,
    *,
    resume_options: dict[str, Any],
    start_options: dict[str, Any],
    ephemeral: bool,
    allow_replacement: bool,
) -> tuple[_SdkThread, str | None]:
    """Start a replacement only when Codex confirms the rollout never existed."""

    try:
        return client.thread_resume(thread_id, **resume_options), None
    except Exception as exc:
        if "no rollout found for thread id" not in str(exc).lower():
            raise
        if not allow_replacement:
            raise
    return client.thread_start(**start_options, ephemeral=ephemeral), thread_id


def _create_official_client(settings: CodexSdkSettings) -> _SdkClient:
    try:
        from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox, TextInput
    except ImportError as exc:
        raise CodexSdkUnavailableError(
            "The official Codex Python SDK is not installed. Install the "
            "forgeos-harness package dependencies or run `pip install openai-codex`."
        ) from exc

    config = CodexConfig(
        codex_bin=str(settings.codex_bin) if settings.codex_bin is not None else None,
        config_overrides=settings.config_overrides,
        cwd=str(settings.workspace),
        client_name="forgeos",
        client_title="ForgeOS",
        client_version="0.1.0",
        experimental_api=False,
    )
    client = Codex(config)
    approval_mode = {
        ApprovalPolicy.deny_all: ApprovalMode.deny_all,
        ApprovalPolicy.auto_review: ApprovalMode.auto_review,
    }[settings.approval_policy]
    sandbox = {
        WorkspaceAccess.read_only: Sandbox.read_only,
        WorkspaceAccess.workspace_write: Sandbox.workspace_write,
    }[settings.workspace_access]
    return _OfficialClientAdapter(
        client,
        approval_mode=approval_mode,
        sandbox=sandbox,
        text_input_type=TextInput,
    )


def _thread_options(
    settings: CodexSdkSettings,
    *,
    developer_instructions: str | None = None,
) -> dict[str, Any]:
    options: dict[str, Any] = {
        "cwd": str(settings.workspace),
    }
    if settings.model is not None:
        options["model"] = settings.model
    actual_instructions = developer_instructions or settings.developer_instructions
    if actual_instructions is not None:
        options["developer_instructions"] = bounded_model_text(
            actual_instructions,
            maximum_bytes=MODEL_ITEM_BYTE_LIMIT,
        )

    return options


def _validate_prompt(prompt: str | ModelInput) -> None:
    if isinstance(prompt, str) and not prompt.strip():
        raise ValueError("prompt must not be empty")


def _prepare_prompt(client: _SdkClient, prompt: str | ModelInput) -> Any:
    bounded = (
        bounded_model_text(prompt, maximum_bytes=MODEL_ITEM_BYTE_LIMIT)
        if isinstance(prompt, str)
        else prompt
    )
    prepare = getattr(client, "prepare_input", None)
    if callable(prepare):
        return prepare(bounded)
    return bounded


def _normalize_turn_result(
    thread_id: str,
    result: Any,
    *,
    replaced_thread_id: str | None = None,
) -> CodexTurnResult:
    error = getattr(result, "error", None)
    return CodexTurnResult(
        thread_id=thread_id,
        turn_id=str(result.id),
        status=_enum_value(result.status),
        final_response=result.final_response,
        error_message=getattr(error, "message", None),
        started_at=result.started_at,
        completed_at=result.completed_at,
        duration_ms=result.duration_ms,
        items=tuple(_object_to_dict(item) for item in result.items),
        usage=_object_to_optional_dict(result.usage),
        replaced_thread_id=replaced_thread_id,
    )


def _collect_controlled_result(
    thread_id: str,
    turn_id: str,
    handle: SdkTurnHandle,
    *,
    on_progress: ProgressCallback | None,
    replaced_thread_id: str | None = None,
) -> CodexTurnResult:
    items: list[Any] = []
    usage: Any = None
    completed_turn: Any = None
    for sequence, event in enumerate(handle.stream(), 1):
        method = str(getattr(event, "method", "unknown"))[:200]
        payload = getattr(event, "payload", None)
        if on_progress is not None:
            on_progress(
                CodexProgressEvent(
                    sequence=sequence,
                    method=method,
                    summary=_progress_summary(method, payload),
                )
            )
        if method == "item/completed" and getattr(payload, "turn_id", None) == turn_id:
            item = getattr(payload, "item", None)
            if item is not None:
                items.append(item)
        elif method == "thread/tokenUsage/updated" and getattr(payload, "turn_id", None) == turn_id:
            usage = getattr(payload, "token_usage", None)
        elif method == "turn/completed":
            turn = getattr(payload, "turn", None)
            if turn is not None and str(getattr(turn, "id", "")) == turn_id:
                completed_turn = turn

    if completed_turn is None:
        raise CodexSdkIntegrationError("turn completed event not received")
    error = getattr(completed_turn, "error", None)
    return CodexTurnResult(
        thread_id=thread_id,
        turn_id=turn_id,
        status=_enum_value(getattr(completed_turn, "status", "unknown")),
        final_response=_final_response(items),
        error_message=getattr(error, "message", None),
        started_at=getattr(completed_turn, "started_at", None),
        completed_at=getattr(completed_turn, "completed_at", None),
        duration_ms=getattr(completed_turn, "duration_ms", None),
        items=tuple(_object_to_dict(item) for item in items),
        usage=_object_to_optional_dict(usage),
        replaced_thread_id=replaced_thread_id,
    )


def _final_response(items: list[Any]) -> str | None:
    fallback: str | None = None
    for item in reversed(items):
        actual = getattr(item, "root", item)
        text = getattr(actual, "text", None)
        if not isinstance(text, str):
            continue
        phase = _enum_value(getattr(actual, "phase", None))
        if phase in {"finalAnswer", "final_answer"}:
            return text
        if phase in {"None", "none"} and fallback is None:
            fallback = text
    return fallback


def _progress_summary(method: str, payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"phase": _progress_phase(method)}
    turn_id = getattr(payload, "turn_id", None)
    if isinstance(turn_id, str):
        summary["turn_id"] = turn_id[:200]
    item = getattr(payload, "item", None)
    if item is not None:
        actual = getattr(item, "root", item)
        item_type = getattr(actual, "type", None)
        if item_type is not None:
            summary["item_type"] = _enum_value(item_type)[:120]
    turn = getattr(payload, "turn", None)
    if turn is not None:
        status = getattr(turn, "status", None)
        if status is not None:
            summary["status"] = _enum_value(status)[:120]
    return summary


def _progress_phase(method: str) -> str:
    if method == "turn/started":
        return "started"
    if method == "turn/completed":
        return "completed"
    if method.startswith("item/"):
        return "tool_or_message"
    if "tokenUsage" in method:
        return "usage"
    if "plan" in method.lower():
        return "planning"
    return "working"


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _object_to_optional_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    return _object_to_dict(value)


def _object_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return dict(value)
    return {"value": value}
