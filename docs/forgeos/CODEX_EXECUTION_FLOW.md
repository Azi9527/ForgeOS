# Codex Execution Flow

本文回答用户输入 `Implement feature X` 后，当前 Codex 内部真实发生的调用链。基线提交为 `068c49f075cf287a1fe7d1ee36cf005efac922e7`。

## 总览

```text
User Input
  ↓
codex CLI / TUI / exec
  ↓
App Server ClientRequest::ThreadStart|ThreadResume, TurnStart
  ↓
MessageProcessor → ThreadProcessor / TurnProcessor
  ↓
ThreadManager → CodexThread → Session
  ↓
Context + World State + Tools Assembly
  ↓
RegularTask → run_turn → ModelClientSession::stream
  ↓
Response items → ToolRouter → ToolCallRuntime → ToolRegistry
  ↓
Hooks / Approval / Sandbox → Tool Handler → Tool Result
  ↓
ConversationHistory → next model sample
  ↓
No follow-up → Stop hook
  ↓ allow                    ↓ block
SessionTask returns          continuation → next model sample
  ↓
EventMsg::TurnComplete
  ↓
ServerNotification::TurnCompleted
  ↓
TUI rendering / exec final output / SDK event
```

## 1. CLI 入口与输入

### 交互模式

1. `codex-rs/cli/src/main.rs::main` 调用 `cli_main`。
2. Clap 解析 `MultitoolCli`；无子命令时调用 `run_interactive_tui`。
3. `codex-rs/tui/src/lib.rs::run_main` 启动或连接 App Server。
4. TUI 将编辑器输入转换为 App Server v2 `turn/start`。

### 非交互模式

1. `MultitoolCli::Exec` 分支调用 `codex_exec::run_main`。
2. `codex-rs/exec/src/lib.rs::run_exec_session` 创建 `InProcessAppServerClient`。
3. 根据参数发出 `ClientRequest::ThreadStart` 或 resume 请求。
4. 发出 `ClientRequest::TurnStart(TurnStartParams)`；随后消费 `InProcessServerEvent`，直到目标 thread/turn 的 `TurnCompleted`。

两个入口共享 App Server 与 core runtime，ForgeOS 不需要为 TUI/exec 分别集成。

## 2. Thread 创建或恢复

1. `app-server/src/message_processor.rs` 将类型化 `ClientRequest` 分派到 `ThreadProcessor`。
2. `thread_processor.rs::thread_start_inner` 校验项目、权限、Sandbox 与配置覆盖。
3. 后台 `thread_start_task` 加载 Config、Trust 和 `ExtensionDataInit`。
4. `ThreadManager::start_thread(StartThreadOptions)` 进入 `start_thread_inner`/`spawn_thread`。
5. `Session::spawn(SessionSpawnArgs)` 创建运行时，绑定 `ThreadStore`、rollout、扩展和历史。
6. `finalize_thread_spawn` 等待首次 `SessionConfigured` 事件，再注册 `CodexThread`。

恢复路径由 `ThreadManager`/`ThreadStore` 读取 rollout，重建 `ConversationHistory`；resume 不等于新 ForgeTask。

## 3. Turn 启动

1. `app-server/src/request_processors/turn_processor.rs::turn_start_inner` 获取 `CodexThread`，校验输入并将 v2 `UserInput` 映射到 core 类型。
2. 构建模型、审批、Sandbox、personality 等 turn settings。
3. 调用 `CodexThread::start_or_steer_turn(TurnInputRequest)`。
4. `core/src/session/turn_input.rs::start_or_steer` 尝试把输入 steer 到活动 turn；空闲时构造 `TurnContext`。
5. `Session::spawn_task(..., RegularTask::new())` 启动普通任务。

## 4. 上下文装配

每个采样步骤由 `capture_step_context` 建立稳定快照：

1. `AgentsMdManager` 刷新可信的 `AGENTS.md`/override。
2. 解析 MCP 工具、动态工具、Skills/Plugins、环境和权限。
3. `build_world_state_for_step` 生成模型、AGENTS、权限、协作、环境、工具及扩展 world-state section。
4. `build_initial_context_with_world_state` 合并 base/developer instructions、`ContextContributor`、world state 和 `ContextualUserFragment`。
5. `record_context_updates_and_set_reference_context_item` 首次写完整上下文，此后记录 world-state diff 并持久化 rollout。
6. `ConversationHistory::for_prompt` 提供模型输入视图；历史只增量构建，工具输出在记录时截断。

如果超过上下文阈值，`run_auto_compact` 走本地或远端 compaction，并触发 PreCompact/PostCompact hook；压缩后的 summary 替换旧提示视图，原始 rollout 仍用于审计/恢复。

## 5. 模型请求和响应

1. `RegularTask::run` 循环调用 `session/turn.rs::run_turn`。
2. `run_turn` 从历史建立 Prompt，并调用 `run_sampling_request`。
3. `try_run_sampling_request` 使用 `ModelClientSession::stream` 请求模型。
4. 流事件由 sampling/stream event 处理代码解析。
5. `stream_events_utils::handle_output_item_done` 处理 assistant message、reasoning 和 function call。
6. Provider 的 `ResponseEvent::Completed { token_usage, end_turn }` 仅结束一次采样；`end_turn == false` 会强制后续采样，并不直接完成 Codex Turn。

## 6. Tool Call 执行

```text
Response function call
  → ToolRouter::build_tool_call
  → ToolCallRuntime::handle_tool_call
  → ToolRegistry::dispatch_tool_call_with_terminal_outcome
  → PreToolUse hook
  → approval / policy / sandbox preparation
  → typed ToolLifecycle start
  → ToolHandler / ToolRuntime
  → typed ToolLifecycle finish
  → PostToolUse hook
  → function_call_output recorded in ConversationHistory
```

Shell 由 unified exec handler/runtime 进入 exec server，并经过 `SandboxManager` 选择的平台 Sandbox。Apply Patch、MCP 和扩展工具进入各自 handler，但共享 Registry 生命周期。PermissionRequest hook、Guardian 和用户审批位于实际执行前；ForgePolicy 适合在 pre-tool/permission 阶段增加约束。

## 7. 下一轮模型

工具结果和新的 pending input 写入历史后，`run_turn` 设置 `needs_follow_up`，再次捕获 StepContext 并调用模型。该循环继续到：

- 没有等待中的工具调用；
- 没有新的用户 steer 输入；
- provider 没有要求继续；
- 不需要先做 compaction；
- Stop hook 同意结束。

## 8. 当前 Completion 条件

完成分为四层，不能混为一个“final”：

| 层 | 条件 | 真实对象 |
| --- | --- | --- |
| Sampling complete | Provider 流返回 Completed | `ResponseEvent::Completed` |
| Agent loop quiescent | 无 tool/pending/follow-up | `session/turn.rs::run_turn` |
| Completion gate | Stop hook 返回 allow；block 时注入 continuation 并继续循环 | `hooks/events/stop.rs`, `hook_runtime::run_turn_stop_hooks` |
| Turn terminal | `SessionTask` 返回，`on_task_finished` 发终态事件 | `EventMsg::TurnComplete(TurnCompleteEvent)` |

`core/src/tasks/mod.rs::on_task_finished` 在正常路径中调用 turn-stop lifecycle contributor，构造 `TurnCompleteEvent { turn_id, last_agent_message, error, timing }`，发送事件并清除活动 turn。终止/取消路径发送 `TurnAborted`。

`app-server/src/bespoke_event_handling.rs::handle_turn_complete` 将无 error 的 core 事件映射为 `ServerNotification::TurnCompleted` 的 Completed 状态，有 error 映射为 Failed；abort 映射为 Interrupted。TUI/exec/SDK 以此作为对外终态。

## 9. ForgeValidation 的最佳接点

M0 推荐两阶段方案：

1. **零 Core 修改原型**：安装受信任 Stop hook。读取 ForgeTask 和 workspace/git evidence，执行验证；PASS 返回 allow，FAIL 返回 block + bounded continuation，使同一个 Codex Turn 进入 repair 循环。
2. **成熟后的窄化类型接口**：只有在外部 hook 的性能、类型安全或原子性不足时，才在 Extension API 增加 `CompletionGateContributor`，调用位置与现有 Stop hook 相邻。不要在 `ThreadIdle` 或 `TurnCompleted` 后再做阻断，因为此时客户端已观察到终态。

ForgeOS 自己的 DONE 仍需 Validation、Review、Acceptance 全部通过。Codex `TurnCompleted` 只表示一次 Agent Turn 结束，不是 ForgeTask 已验收。
