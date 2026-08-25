# ForgeOS Extension Points

本文只设计扩展，不在 M0 实现。当前源码已存在两套互补机制：

- **Hooks**：命令/MCP/Prompt/Agent handler，可做阻断、改写和外部集成。
- **Extension API**：进程内类型化 Contributor，适合生命周期观测、上下文、工具、状态和审计。

因此不建议先增加通用 `RuntimeHook`。ForgeOS 应组合现有机制，并只为没有表达能力的“类型化完成门”保留一个窄化补丁候选。

## 机制选择原则

| 需要 | 首选 | 原因 |
| --- | --- | --- |
| 观察 Thread/Turn/Tool | Extension lifecycle contributor | 类型安全、低序列化成本、已随 ThreadManager 安装。 |
| 注入模型上下文 | ContextContributor / TurnInputContributor | 使用受控 `ContextualUserFragment` 和 world-state diff。 |
| 阻断/重写工具 | PreToolUse / PermissionRequest / PostToolUse hook | 当前 ToolLifecycle contributor 明确偏观察。 |
| 阻止 Agent 结束并修复 | Stop hook | 已在 `run_turn` 的终态前运行，支持 continuation。 |
| 外部控制 | Python SDK | ForgeOS 先使用官方类型化 Thread/Turn API；App Server 是其底层控制面。 |
| Forge 持久状态 | 独立 `.forge/` repository | Git 可见、可恢复，不污染 rollout 或 Codex config。 |

## EP-01 Before Task

**目的**：创建/加载 ForgeTask、ForgeRules、ForgeContext、已接受 Memory，记录 Git baseline。

Codex 没有 ForgeTask 概念；App Server `thread/start` 也太偏底层。M1 应在独立 `forge` CLI 中先完成前置事务，再启动/关联 Codex Thread：

```text
forge task run FORGE-0001
  → load .forge/forge.yaml
  → validate task state transition
  → snapshot git HEAD + working tree metadata
  → append audit event
  → start/resume Codex thread through App Server
```

进程内可用 `ThreadLifecycleContributor::on_thread_start/on_thread_ready` 做关联校验和 audit，但它不是创建 ForgeTask 的唯一权威入口。

**推荐**：Python service + `.forge/` 文件事务作为权威入口；CLI 只调用一次 service 操作。后续优先通过 `CodexSdkGateway` start/resume thread，只有 SDK gap 被证明后才安装 App Server extension。

## EP-02 Context Assembly

**目的**：注入 ForgeProject、ForgeTask、ForgeRules、ForgeMemory。

最佳位置是 `codex-extension-api`：

- `ContextContributor::contribute_thread_context`：稳定的 Project identity 和少量固定规则索引。
- `ContextContributor::contribute_turn_context`：当前 ForgeTask、状态、验收条件和预算。
- `ContextContributor::contribute_world_state`：可能变化的 git/validation/task state，以稳定 section ID 支持 diff。
- `TurnInputContributor`：仅对本次提交有效的短期补充。

每个 fragment 必须有硬上限、稳定的 `content_kind`/边界标记，并实现 `ContextualUserFragment`。完整规则或日志留在 `.forge/`，模型只接收必要摘要与可定位路径。

## EP-03 Before Turn

**目的**：检查 Task State、Policy、Budget、Context Refresh。

候选链：

1. Forge 控制层在发送 `turn/start` 前检查状态机和预算。
2. `TurnLifecycleContributor::on_turn_start` 记录内部 turn ID 与 ForgeTask 关联。
3. `ContextContributor` 在采样前提供刷新后的可变状态。
4. `UserPromptSubmit` hook 对用户输入做外部策略检查。

`on_turn_start` 是观察性生命周期，不应单独承担阻断；阻断必须在控制层或 hook 完成。

## EP-04 After Turn

**目的**：Audit、State Update、Progress。

- `TurnLifecycleContributor::on_turn_stop/on_turn_abort/on_turn_error`：记录类型化终态。
- `TurnItemContributor`：记录模型/工具 item 的受控摘要。
- `TokenUsageContributor`：记录 token/budget 使用量。
- `ThreadLifecycleContributor::on_thread_idle`：标记线程空闲，但该事件在 core TurnComplete 之后，只适合观察。
- App Server `turn/completed`：供进程外控制层归并状态。

Audit 必须对命令、环境、模型输出和 tool payload 做 allowlist/redaction；不得把凭证或完整敏感输出无界复制进 `.forge/`。

## EP-05 Before Tool Call

**目的**：Policy Check、Risk Check、Audit。

真实执行点在 `ToolRegistry`：先执行 PreToolUse hook，再进入审批/执行和类型化 ToolLifecycle start。建议：

- PreToolUse hook：允许、拒绝或重写；检查 ForgePolicy 和 task scope。
- PermissionRequest hook：在 Codex 自身审批流前给出额外安全判断。
- `ToolLifecycleContributor::on_tool_start`：只记审计和关联 ID。

ForgePolicy 只能收紧 Codex Sandbox/Approval；不能把 Codex `Forbidden` 变为允许，也不能代替平台 Sandbox。

## EP-06 After Tool Call

**目的**：Audit、Changed File Detection、Command Result、Failure Detection。

- `ToolLifecycleContributor::on_tool_finish` 获得工具终态，适合结构化审计。
- PostToolUse hook 可以补充上下文或阻断不可信结果。
- Changed file detection 不只依赖工具名：工具可通过 Shell 间接修改文件。应在验证边界读取 `git status --porcelain=v2`/diff，并和 EP-01 baseline 比较。
- 失败分为 tool error、process exit、Sandbox denial、approval denial、timeout；Audit 保留类别、时间、摘要和证据引用。

## EP-07 Agent Completion

**目的**：在 Codex Turn 对外完成前执行独立 ForgeValidation，并在失败时进入修复。

### 当前真实位置

```text
run_turn sees no follow-up
  → run_turn_stop_hooks
      ├─ allow: break and return last_agent_message
      └─ block: record continuation and sample again
  → RegularTask returns
  → Session::on_task_finished
  → TurnLifecycleContributor::on_turn_stop
  → EventMsg::TurnComplete
  → App Server turn/completed
```

### M0 推荐

使用现有 Stop hook 实现第一版 completion gate：

```text
Agent loop quiescent
  → Forge Stop validator
      ├─ PASS → Review/Acceptance orchestration → allow
      └─ FAIL → write validation evidence → block + repair continuation
```

Stop hook 收到 session/turn/cwd/transcript/model/permissions/last message 等上下文，能在终态事件之前阻断，且 M0/M1 无需改 Codex Core。

### 可能的后续最小补丁

如果验证需要进程内强类型状态、不可绕过的原子性或显著降低进程开销，可在 `codex-extension-api` 增加专用的 `CompletionGateContributor`：

- 输入：线程/turn 标识、最后消息、只读 scoped state、取消 token。
- 输出：`Allow` 或 `Block { bounded_continuation, evidence_ref }`。
- 调用点：`session/turn.rs` 现有 Stop hook 相邻位置。
- 约束：不改变 `TurnLifecycleContributor` 的观察语义，不让 extension 直接放宽 Sandbox/Approval。

该补丁在实现前必须登记 `UPSTREAM_PATCHES.md` 并以集成测试证明 PASS、FAIL→REPAIR、取消和 resume 行为。

## 扩展点结论

| EP | M1/M2 可用机制 | 预计 Core 修改 |
| --- | --- | --- |
| EP-01 Before Task | Forge CLI + `.forge/`，Thread lifecycle 观察 | 无 |
| EP-02 Context | Context/TurnInput Contributor | 无；需安装 Forge extension |
| EP-03 Before Turn | Forge control + Turn lifecycle + hook | 无 |
| EP-04 After Turn | Turn/Thread/Token/Item Contributor + App Server event | 无 |
| EP-05 Before Tool | PreToolUse/PermissionRequest + Tool lifecycle | 无 |
| EP-06 After Tool | PostToolUse + Tool lifecycle + Git diff | 无 |
| EP-07 Completion | Stop hook；以后可选 typed completion gate | 原型无；成熟方案可能 1 个窄补丁 |
