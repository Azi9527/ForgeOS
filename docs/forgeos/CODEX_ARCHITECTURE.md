# Codex Architecture Map

本地图对应提交 `068c49f075cf287a1fe7d1ee36cf005efac922e7`。路径均相对于仓库根目录；结论来自当前源码，而不是历史版本或外部文章。

## 1. Repository Map

| 路径 | 职责 |
| --- | --- |
| `codex-rs/` | Rust 主工作区：CLI、TUI、App Server、Agent Runtime、工具、安全、持久化与扩展。 |
| `codex-cli/` | npm 包 `@openai/codex` 的平台二进制分发启动器；不是核心 Agent Loop。 |
| `sdk/typescript/` | 通过 Codex CLI 的 JSONL 接口启动/恢复线程。 |
| `sdk/python/` | App Server JSON-RPC 的类型化 Python 客户端。 |
| `docs/` | 安装、配置、Sandbox、贡献等官方开发文档。 |
| `scripts/`, `tools/` | 格式化、构建、发布和仓库维护脚本。 |
| `justfile`, `MODULE.bazel` | Cargo/Just 与 Bazel 构建入口。 |

## 2. Crate / Module Map

| Crate | 真实路径 | 主要职责 |
| --- | --- | --- |
| `codex-cli` | `codex-rs/cli` | `codex` 多命令入口和参数解析。 |
| `codex-tui` | `codex-rs/tui` | 交互式终端 UI；当前作为 App Server 客户端。 |
| `codex-exec` | `codex-rs/exec` | 非交互执行和 JSONL 输出；当前使用进程内 App Server 客户端。 |
| `codex-app-server` | `codex-rs/app-server` | 控制面、JSON-RPC/InProcess 请求处理、Thread/Turn 编排。 |
| `codex-app-server-protocol` | `codex-rs/app-server-protocol` | 类型化 v2 请求、响应、通知和生成的 TypeScript API。 |
| `codex-core` | `codex-rs/core` | Session、Turn、采样循环、上下文、工具路由和权限编排。 |
| `codex-core-api` | `codex-rs/core-api` | 可共享的核心 API 类型，降低对 `codex-core` 的依赖。 |
| `codex-protocol` | `codex-rs/protocol` | 核心事件、操作、审批与 Sandbox 协议。 |
| `codex-thread-store` | `codex-rs/thread-store` | 存储中立的 ThreadStore、LiveThread 和元数据同步。 |
| `codex-rollout` | `codex-rs/rollout` | JSONL rollout 记录、恢复和查找。 |
| `codex-tools` | `codex-rs/tools` | 跨运行时共享的模型可见工具契约与数据模型。 |
| `codex-hooks` | `codex-rs/hooks` | 外部命令/MCP/Prompt/Agent hook 执行和决策。 |
| `codex-extension-api` | `codex-rs/ext/extension-api` | 类型化 Contributor、ExtensionRegistry 和作用域状态。 |
| `codex-config` | `codex-rs/config` | 分层配置加载、schema 类型与受管约束。 |
| `codex-sandboxing` | `codex-rs/sandboxing` | 平台 Sandbox 选择、进程变换和启动。 |
| `codex-exec-server` | `codex-rs/exec-server` | 实际命令执行服务和跨进程执行边界。 |
| `codex-mcp`, `codex-mcp-server` | `codex-rs/codex-mcp`, `codex-rs/mcp-server` | MCP 连接管理和 Codex MCP 服务端。 |

工作区还包含 App Server transport/client/daemon、Linux/Windows Sandbox、登录、网络代理、技能、图像、Web Search、Guardian、Memory 等专用 crate。M0 不需要复制这些能力。

## 3. CLI Architecture

`codex-rs/cli/src/main.rs` 中的 `MultitoolCli` 使用 Clap 定义顶层命令。`main()` 经 `arg0_dispatch_or_else` 进入 `cli_main()`：

- 无子命令或 `agents`：`run_interactive_tui()` → `codex_tui::run_main()`。
- `exec`/`review`：`codex_exec::run_main()`。
- `app-server`：`codex_app_server::run_main_with_transport_options()`。
- 还包括 MCP、login、sandbox、apply-patch、exec-server 等工具命令。

`codex-rs/tui/src/lib.rs` 的 TUI 会启动或连接 App Server。`codex-rs/exec/src/lib.rs::run_main` 构造 `InProcessAppServerClient`，由 `run_exec_session` 发送 `thread/start`、`thread/resume` 和 `turn/start`。因此交互和非交互路径在当前版本都汇聚到 App Server，而不是分别维护 Agent Loop。

## 4. Core Runtime

核心运行时由以下对象协作：

- `core/src/thread_manager.rs::ThreadManager`：创建、恢复、注册和查找线程；`start_thread`/`start_thread_inner`/`spawn_thread` 调用 `Session::spawn`。
- `core/src/codex_thread.rs::CodexThread`：App Server 可持有的线程句柄；提供 `submit`、`start_or_steer_turn`、`next_event`。
- `core/src/session/session.rs::Session`：已加载线程的运行时状态、配置、历史、活动任务、事件通道和扩展。
- `core/src/tasks/mod.rs::SessionTask`：一次可执行任务的抽象；`Session::start_task` 运行任务并由 `on_task_finished` 生成终态事件。
- `core/src/tasks/regular.rs::RegularTask`：普通用户 Turn，循环调用 `run_turn`。
- `core/src/session/turn.rs::run_turn`：实际模型/工具循环。

`app-server/src/message_processor.rs::MessageProcessor::new` 是进程级组合根：创建 `ThreadStore`、队列、`ThreadManager`，并通过 `app-server/src/extensions.rs::thread_extensions` 安装内置扩展。

## 5. Agent Loop

`RegularTask::run` 发出 TurnStarted 后循环调用 `session/turn.rs::run_turn`。`run_turn`：

1. 刷新 AGENTS、MCP、工具和环境，建立 `StepContext`。
2. 记录用户输入、世界状态及扩展上下文。
3. 必要时执行自动压缩。
4. 从 `ConversationHistory::for_prompt` 生成 Prompt。
5. `run_sampling_request`/`try_run_sampling_request` 调用 `ModelClientSession::stream`。
6. `stream_events_utils::handle_output_item_done` 将函数调用交给 `ToolRouter`，并排队到 `ToolCallRuntime`。
7. 工具结果写回历史后进入下一次采样。
8. 若无待处理工具/输入且 provider 没有要求继续，则运行 Stop hook；hook 可阻止结束并注入 continuation。
9. Stop 放行时返回最终消息；`SessionTask` 完成后由 `on_task_finished` 发出 `EventMsg::TurnComplete`。

## 6. Tool Runtime

| 层 | 真实实现 |
| --- | --- |
| 工具规划 | `core/src/tools/spec_plan.rs::build_tool_router` 根据模型、Features、环境、MCP 和扩展构造可见工具。 |
| 请求识别 | `core/src/tools/router.rs::ToolRouter::build_tool_call` 把模型输出映射为工具调用。 |
| 并发与取消 | `core/src/tools/parallel.rs::ToolCallRuntime` 控制并发、取消并调用 Registry。 |
| 分发与生命周期 | `core/src/tools/registry.rs::ToolRegistry` 依次执行 pre-tool hook、审批/生命周期、handler、post-tool hook。 |
| Shell | `core/src/tools/handlers/unified_exec.rs` 和 `core/src/tools/runtimes/unified_exec.rs::UnifiedExecRuntime`；底层经 exec server 和平台 Sandbox。 |
| Patch | `core/src/tools/handlers/apply_patch.rs`、`core/src/tools/runtimes/apply_patch.rs`、`codex-rs/apply-patch`。 |
| Search/Read | 由模型可见 handler、统一 exec 以及专用搜索/上下文工具组合提供。 |
| MCP | `core/src/tools/handlers/mcp.rs` → `mcp_tool_call` → `codex_mcp::McpBinding`/连接管理器。 |
| 外部扩展工具 | `codex-extension-api::ToolContributor` 和 `core/src/tools/handlers/extension_tools.rs`。 |

`codex-tools` 提供可共享的 `ToolSpec`、`ToolCall`、`ToolOutput`、`ToolExecutor` 等契约；Session、审批和重试仍由 `codex-core` 编排。

## 7. Context

- **Base/System Instructions**：模型配置和 `Prompt.base_instructions`；`core/src/client.rs::build_responses_request` 映射为 Responses API instructions。
- **Developer Instructions**：Session 配置与 `build_initial_context_with_world_state` 中的 developer-role 内容。
- **User Input**：App Server v2 `TurnInput` 映射到 core 输入，写入 `ConversationHistory`。
- **Repository Instructions**：`core/src/agents_md.rs::load_project_instructions` 从项目根到 cwd 搜索 `AGENTS.override.md`/`AGENTS.md`，受信任时才加载并有字节上限。
- **World State**：`core/src/session/world_state.rs::build_world_state_for_step` 汇集模型、权限、环境、AGENTS、工具和扩展 section。
- **Forge 可用入口**：`ContextContributor` 提供 thread/turn/world-state fragment；`TurnInputContributor` 提供每次输入的 `ContextualUserFragment`。
- **历史**：`core/src/context_manager/history.rs::ConversationHistory` 负责记录、提示视图、token 估计及工具输出截断。
- **压缩**：`core/src/compact.rs`、`compact_remote.rs`、`compact_remote_v2.rs` 与 `run_auto_compact`；存在 PreCompact/PostCompact hooks。

所有新增模型上下文必须是有上限、稳定标识、可增量构建的 `ContextualUserFragment`，不能用无界字符串拼接重写历史。

## 8. Sandbox

`codex-protocol` 定义 `SandboxPolicy` 和新的 `permissions.rs` 文件/网络策略。策略支持只读、工作区写、外部 Sandbox 和完全访问；`.git`、`.agents`、`.codex` 等元数据目录有特殊保护。

`codex-sandboxing/src/manager.rs::SandboxManager` 将逻辑策略转换为平台执行方式：macOS Seatbelt、Linux bwrap/seccomp、Windows Restricted Token 或外部 Sandbox。`core/src/tools/sandboxing.rs` 负责工具尝试、Sandbox 失败与可能的审批重试。ForgePolicy 只能增加工程约束，不能绕开此机械边界。

## 9. Approval

`protocol/src/protocol.rs::AskForApproval` 包含 `UnlessTrusted`、`OnRequest`、`Granular`、`Never`。`core/src/exec_policy.rs::ExecPolicyManager` 合并配置规则和危险命令启发式，产出 `Skip`、`NeedsApproval` 或 `Forbidden`。

`core/src/tools/approvals.rs::Session::request_approval` 的决策顺序是 PermissionRequest hook、可选 Guardian 自动审查、用户审批。审批结果可以是一次批准、会话批准、策略修订、网络修订、拒绝、超时或终止。App Server 把需要人的审批转换为 server request。Agent 的请求本身不构成授权。

## 10. Session

- **Thread**：持久化的对话标识；由 `ThreadId` 寻址。
- **Session**：某个 Thread 加载后的内存运行时。
- **Turn**：从一次用户输入到 Completed/Failed/Interrupted 的操作。
- **SessionTask**：执行 Turn、Review、Compact 等工作流的内部任务抽象，不等于 ForgeTask。
- **Rollout**：`codex-rollout` 管理的 JSONL 历史记录。

`codex-thread-store::ThreadStore` 是存储中立接口，`LiveThread` 创建/恢复并追加 rollout item，同时通过 SQLite 元数据索引支持列表和查询。`ThreadManager` 从 rollout 恢复 ConversationHistory；SDK 可使用 thread ID resume。

## 11. Config

`codex-config/src/loader` 以低到高顺序合并系统、企业云、用户 `~/.codex/config.toml`、用户 profile、项目 `.codex/config.toml`、SessionFlags 和受管配置；不可信项目层可被禁用。`config/src/config_toml.rs::ConfigToml` 定义模型、Sandbox、审批、hooks 等 schema，`core/src/config/mod.rs::ConfigBuilder` 解析运行时 Config。

Forge 的 `.forge/forge.yaml` 是独立工程协议，不应伪装成 `.codex/config.toml`。只有需要驱动 Codex 的部分通过类型化 integration 或明确的 harness override 映射。

## 12. App Server

`codex-app-server` 暴露稳定的 stdio JSON-RPC 和进程内调用；WebSocket 仍是实验性/不受支持入口。主要链路是：

```text
MessageProcessor
  → initialized ClientRequest dispatch
  → ThreadProcessor / TurnProcessor
  → ThreadManager / CodexThread
  → core Event
  → bespoke_event_handling
  → ServerNotification
```

v2 支持 `thread/start|resume|fork`、`turn/start`、item/turn 通知、review、config 等；部分 Project/Memory/Goal API 是实验性。由于 TUI、exec 和 Python SDK 都已围绕 App Server，建议将其作为 ForgeOS 未来控制面入口，但 M1 ForgeProject 不依赖实验性 Codex Project API。

## 13. SDK

- **TypeScript SDK**：启动 Codex CLI，读取 JSONL；适合外部 Node 自动化和 thread resume，但生命周期接入较粗。
- **Python SDK**：App Server JSON-RPC 类型化客户端；适合控制层原型、集成测试和异构服务。
- **Rust Extension API**：不是单独品牌 SDK，但对进程内上下文、工具和 lifecycle 集成最强。

结论：ForgeOS 当前外部控制统一使用 Python SDK；SDK 底层复用 App Server。原始 App Server、Rust Extension API 和 TypeScript SDK 都不是第一阶段入口，只有公共 SDK 出现可验证缺口时才增加更深适配。

## 14. Event / Hook

`codex-hooks` 当前支持 PreToolUse、PermissionRequest、PostToolUse、PreCompact、PostCompact、SessionStart、SessionEnd、UserPromptSubmit、SubagentStart、SubagentStop、Stop。Stop hook 能以结构化结果或退出码阻止完成并提供 continuation。

`codex-extension-api` 提供类型化 Contributor：ThreadLifecycle、TurnLifecycle、ToolLifecycle、TurnItem、Context、TurnInput、Tool、MCP、ApprovalReview、Config、TokenUsage、SkillInvocation 等。`app-server/src/extensions.rs::thread_extensions` 是安装点。

边界限制：`TurnLifecycleContributor::on_turn_stop` 当前只观察，不能阻止完成；`ToolLifecycleContributor` 也主要用于观察，不应承担改写/阻断策略。策略与完成门优先复用 hooks；若将来需要强类型进程内验证，再增加一个窄化的 completion gate，而不是通用 middleware。
