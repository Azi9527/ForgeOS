# ForgeOS Development Standards

## 1. 文档目的与适用范围

本规范定义 ForgeOS V1 的工程开发规则，适用于：

- ForgeOS 自有 Rust crate、CLI、文件协议和测试；
- ForgeOS 与 Codex App Server、Extension API、Hooks 的集成；
- 对 OpenAI Codex 上游文件的必要修改；
- `.forge/` 中的配置、Task、Workflow、Validation、Memory 和 Audit 数据；
- 设计、实现、评审、验证、发布与 upstream 同步过程。

本规范不授权开发 V1 非目标，包括复杂 Multi-Agent、Model Router、Web Console、SaaS、向量数据库、复杂 RAG、分布式执行和大型数据库。

## 2. 规范用语

- **MUST / 必须**：违反即不能合并、发布或进入下一状态。
- **MUST NOT / 禁止**：明确不允许。
- **SHOULD / 应当**：默认必须遵循；偏离时需要在 Task 或 ADR 中记录理由。
- **MAY / 可以**：在不破坏 MUST 约束时可自行选择。

## 3. 需求与事实来源优先级

发生冲突时按以下顺序处理：

1. 当前用户明确指令。
2. `ForgeOS_REQUIREMENTS_V1.0.md` 的产品语义和范围。
3. 当前 checkout 的 Codex 真实源码行为。
4. 仓库根 `AGENTS.md` 及子目录开发规则。
5. `docs/forgeos/` 已接受的架构决策。
6. 其他说明、历史文章或个人记忆。

需求对 Codex 内部结构的假设与真实源码冲突时，MUST 以真实源码设计实现，但 MUST 在 ForgeOS 文档或 ADR 中记录差异；禁止静默改变需求语义。

## 4. 核心工程原则

所有设计和评审必须回答以下问题：

| 原则 | 强制问题 |
| --- | --- |
| Maximum Reuse | Codex 是否已经提供 runtime、tool、sandbox、approval、MCP、context、session 或 SDK 能力？ |
| Minimum Intrusion | 能否用新 Forge crate、Extension API、Hook 或 App Server adapter 完成？ |
| Upstream Friendly | 上游更新时，此修改能否独立识别、验证和删除？ |
| Harness > Prompt | 关键行为是否由 schema、状态机、policy 和 validation 执行，而不是提示词约定？ |
| Agent != Authority | Agent claim 是否被错误地当成工程状态或验收证据？ |
| Validation First | Task 是否在实现前定义可执行验收条件？ |
| Observable / Recoverable | 失败后能否从文件、Git baseline 和 audit 重建真实状态？ |

## 5. Codex / ForgeOS 边界规范

### 5.1 Codex Owned

ForgeOS MUST 复用而不是重新实现：

- Agent Loop、模型通信和 tool calling；
- Shell、Apply Patch、文件编辑、搜索和 MCP；
- Sandbox、Approval、Guardian 和 authentication；
- AGENTS.md、base context、history 和 compression；
- Thread、Session、Turn、rollout persistence 和 resume；
- CLI/TUI/exec/App Server/SDK 基础设施。

### 5.2 ForgeOS Owned

ForgeOS 拥有 Project、Task、Rules、Context selection、Workflow、Validation、Regression、Review、accepted Memory、Audit、Policy 和 Acceptance 的工程语义。

Codex `TurnCompleted` MUST NOT 直接导致 ForgeTask `DONE`。Codex Review/Memory/Project 等同名能力可以作为机制复用，但不能成为 Forge 状态权威。

### 5.3 依赖方向

允许的依赖方向：

```text
forgeos domain/service
  ↑
CodexSdkGateway / validation services
  ↑
openai-codex Python SDK
  → Codex App Server / Runtime
```

强制约束：

- ForgeOS Python domain MUST NOT 依赖 `codex-core` 或 Codex 内部 Rust module。
- `codex-core` MUST NOT 依赖 ForgeProject、ForgeTask 或 `.forge` persistence。
- Forge integration MUST 优先依赖官方 Python SDK 公共 API，而不是原始 JSON-RPC 或内部大模块。
- M1 MUST NOT 修改 Agent Loop、Shell、Sandbox、Approval、MCP 或 Context Runtime。

## 6. 源码组织规范

推荐初始结构：

```text
forgeos/
├─ pyproject.toml
├─ src/forgeos/           # domain, service, SDK adapter
└─ tests/                 # isolated and opt-in integration tests
```

模块规范：

- Python package 名为 `forgeos-harness`，import package 固定为 `forgeos`。
- store/audit 先作为职责清晰的 package 私有模块；没有独立复用和依赖边界时禁止拆小 package。
- 模块默认 private，只从 `forgeos.__init__` 显式导出稳定 API。
- Python 模块目标少于 500 行；接近 800 行时 MUST 拆分新模块，除非有书面理由。
- 禁止把新 Forge domain 概念放进 `codex-core` 以图方便。
- 禁止创建只调用一次、没有抽象价值的小 helper。
- 文件名、模块名和领域名必须一致，禁止 `utils`, `common`, `manager` 等无明确所有权的垃圾抽屉模块。

若以后确需修改 Rust，上游 `AGENTS.md` 的 Rust、Cargo、Bazel 和测试规则对该 patch 完整生效；它们不是纯 Python ForgeOS change 的默认工具链要求。

## 7. 开发工作流规范

任何实质性代码修改 MUST 归属于一个 ForgeTask。标准工作流：

```text
Understand
→ Inspect current source
→ Impact Analysis
→ Plan
→ Implement
→ Build
→ Test
→ Regression
→ Review
→ Acceptance
```

开始实现前 MUST 完成：

1. 明确 objective、scope、constraints 和 acceptance。
2. 阅读目标代码和适用的 `AGENTS.md`。
3. 搜索已有 crate、trait、hook、event 和测试工具。
4. 记录 Git branch、HEAD、working tree 和 baseline diff。
5. 列出预计修改文件和 Codex/ForgeOS owner。
6. 若涉及上游文件，先登记 Proposed Patch。
7. 确认测试层级和失败恢复方式。

实现过程中禁止：

- 为通过测试而删除或放宽现有测试；
- 用跳过测试掩盖根因；
- 降低 Sandbox、Approval 或 policy；
- 无理由大规模重构或 branding 替换；
- 删除用途不明的代码；
- 把多个不相关变更塞进同一 Task/commit；
- 在发现设计问题后静默改写需求。

## 8. ForgeProject 与 ForgeConfig 规范

ForgeProject MUST 至少表示：

```text
id, name, description, root, language, framework,
repository, default_branch
```

规范：

- `root` MUST canonicalize，并验证位于当前受管 workspace 内。
- repository identity SHOULD 使用 normalized remote + project ID，不只依赖目录名。
- `forge.yaml` MUST 包含可判定的 schema/version 字段。
- 配置解析 MUST 拒绝未知 major version、类型错误和不安全路径。
- 默认值 MUST 在 schema、代码和文档中一致；不得由调用点各自猜测。
- 配置错误 MUST 指出字段路径、无效值类别和修复建议，但 MUST NOT 输出秘密。
- Forge config 与 `.codex/config.toml` MUST 保持不同所有权；映射到 Codex config 时必须显式、单向、可审计。

## 9. ForgeTask 领域规范

### 9.1 必需字段

ForgeTask MUST 支持需求基线字段：

```text
id, title, type, objective, background, scope, constraints,
acceptance, related_modules, priority, risk_level, status,
created_at, updated_at
```

持久化实现还 SHOULD 包含 `schema_version` 和 `revision`，用于迁移和并发控制。

Task Type 只允许：

```text
FEATURE, FIX, REFACTOR, REVIEW, DOC, TEST
```

所有字符串、集合和嵌套对象 MUST 有显式大小上限。时间 MUST 使用 UTC，并在 schema 中固定格式。Task ID MUST 使用配置的 prefix 和固定宽度序号，例如 `FORGE-0001`。

### 9.2 状态机

正常路径：

```text
CREATED → ANALYZING → PLANNED → IMPLEMENTING → VALIDATING
→ REVIEWING → ACCEPTING → DONE
```

修复路径：

```text
VALIDATING → REPAIRING → VALIDATING
```

异常状态：

```text
BLOCKED, FAILED, CANCELLED
```

规范：

- 所有状态写入 MUST 经过 `TaskStateMachine`。
- Agent、CLI renderer、Codex event handler MUST NOT 直接写 status。
- 转换 API MUST 同时校验 expected revision、source state、target state、actor、reason 和 required evidence。
- 非法转换 MUST 在写盘前失败，不能留下部分 audit 或半更新 Task。
- 异常状态的进入和恢复 MUST 使用显式转换表；禁止 wildcard transition。
- `DONE` MUST 是终态，除非未来 schema migration 明确引入 reopen 语义。
- `DONE` 必须具备 Implementation、Build、Required Tests、Regression、Review 和 Acceptance 全部 PASS 的证据。

## 10. ForgeRules、ForgeContext 与 ForgeWorkflow 规范

### 10.1 ForgeRules

Rule 层级必须按以下顺序解析，并保留每条规则的来源：

```text
Global → Project → Module → Task
```

Rule schema MUST 包含 `id`, `name`, `scope`, `severity`, `description`, `enforcement`。severity 只允许 `INFO`, `WARNING`, `BLOCK`。

- rule ID MUST 在项目内稳定、唯一，重命名不能静默创建不同规则。
- 合并结果 MUST 确定性；同一 scope 的冲突必须报告，不能依赖文件遍历顺序。
- 更具体层可以补充规则，但 MUST NOT 静默降级更高层的 `BLOCK`。
- `enforcement` MUST 区分 prompt guidance、validator、policy gate；不能把 Rule 文本冒充机械 Policy。
- 每次 Context Package MUST 记录实际生效的 rule ID/version，而不是只复制自然语言。

### 10.2 ForgeContext

Context Package 的候选来源包括 Project Description、Architecture、Module Map、Task、Rules、Related Code、Recent Changes、Decisions、Failures、Patterns 和 Tests。

持久或运行时表示 MUST 能表达：

```text
project, task, architecture, rules, related_files,
decisions, failures, validation
```

Context builder 必须：

- 先根据 Task scope 选择，再按 relevance/freshness 排序，最后在硬预算内裁剪；
- 对每个 fragment 记录 source、version/hash、selected reason、size 和 truncation；
- related file 只记录项目内 normalized path；
- 把不可信源码/外部文本与 developer authority 分开；
- 相同输入产生确定性 package，除非明确包含 current time/world state；
- Context 构建失败结构化记录，禁止回退为“读取整个仓库”。

### 10.3 ForgeWorkflow

V1 workflow type 至少支持 `feature`, `fix`, `refactor`, `review`。默认工程步骤：

```text
Understand → Inspect → Impact Analysis → Plan → Implement
→ Build → Test → Regression → Review → Acceptance
```

Workflow schema MUST versioned，并至少定义 name、steps、每步输入/输出、进入条件、成功/失败转移、retry/budget 和 resumability。

- step name MUST 稳定，用于 ExecutionStepResult 和 audit correlation。
- 完成状态必须由 step result/evidence 推导，不能由 Agent 自报。
- retry MUST 只重跑声明为幂等或具有补偿动作的 step。
- resume MUST 从最后一个 committed step boundary 继续。
- workflow 变更对 active Task 的处理必须明确：固定原版本、显式迁移或拒绝 resume，禁止静默切换。

## 11. `.forge/` 文件协议规范

目录布局以 [FORGEOS_ARCHITECTURE.md](FORGEOS_ARCHITECTURE.md) 为准。协议规则：

### 11.1 编码和格式

- 文本 MUST 为 UTF-8；仓库持久文件 SHOULD 使用 LF。
- YAML/JSON 字段名 MUST 稳定，禁止仅为代码重命名而破坏持久 schema。
- JSONL 每行 MUST 是一个完整事件；禁止跨行对象。
- map 输出 SHOULD 使用确定性字段顺序，减少 Git 噪音。
- 浮点数、locale-dependent 时间和平台专属绝对路径 SHOULD 避免进入协议。

### 11.2 原子性和并发

- 对象更新 MUST 使用同目录临时文件、flush、原子 rename；禁止原地截断后写入。
- 写入 MUST 检查 expected revision，冲突返回结构化 concurrency error。
- Task ID 分配 MUST 在并发进程间安全，不能通过“扫描最大文件名再无锁写入”实现。
- Task 投影移动到 `active/completed/failed` 时，状态更新、目标写入和 audit MUST 具有可恢复顺序。
- 崩溃恢复 MUST 能区分 committed、temporary 和 corrupt 文件；不得静默丢弃损坏记录。

### 11.3 路径安全

- 所有相对路径 MUST 基于 canonical ForgeProject root 解析。
- 禁止 `..`、绝对路径注入、symlink escape 和写入 `.git`/项目外目录。
- 删除、移动或覆盖前 MUST 验证最终 canonical target。
- `forge init` MUST NOT 覆盖现有非 Forge 文件；重复执行必须幂等。

### 11.4 版本和迁移

- 每个持久对象 MUST 携带 `schema_version`，或由父协议提供无歧义版本。
- reader SHOULD 支持当前版本和明确声明的旧版本；未知新版本 MUST fail closed。
- migration MUST 可重复、可测试、保留备份或提供 recoverable transaction。
- schema 变更 MUST 包含 fixture、migration test、兼容性说明和 rollback 策略。

## 12. ForgeExecution、Validation 与 Review 规范

### 12.1 ExecutionStepResult

每个执行步骤 MUST 记录：

```text
name, status, started_at, finished_at, input, output,
files_read, files_changed, commands, error
```

input/output MUST 有大小上限；大型内容保存为 evidence file，并在结果中记录 path、hash、size 和 redaction 状态。

### 12.2 Validation

Validation Level：

```text
L1 Build
L2 Unit Test
L3 Integration Test
L4 Regression
L5 Acceptance
```

ValidationResult MUST 包含 validator、status、command、start/end time、output/evidence、error。状态只允许 `PASS`, `FAIL`, `SKIP`, `ERROR`。

- `SKIP` MUST 包含 policy-authorized reason；required validator 的 SKIP 不能满足 DONE。
- `ERROR` 表示验证器无法可靠判定，不得当作业务 FAIL 或 PASS。
- 任何 PASS MUST 来源于直接执行或受信任、可验证的外部 evidence，不能来源于 Agent 文本。
- 验证命令和工作目录 MUST 在执行前被解析、记录并经过 Codex/host 安全边界。
- Repair 默认最多 3 次；达到预算后 MUST 进入 BLOCKED，而不是继续循环。

### 12.3 Review 与 Acceptance

Review 至少检查 Architecture、Code Quality、Risk、Tests、Backward Compatibility 和 Technical Debt。Review 与 Validation 必须是不同结果对象：Validation 回答“能否工作”，Review 回答“实现是否合理”。

Acceptance MUST 对 Task acceptance criteria 逐项给出 PASS/FAIL/evidence。只有 Acceptance policy 或授权人能够推动 `ACCEPTING → DONE`。

### 12.4 Forge Task Report

最终报告 MUST 至少包含：

```text
Task, Objective, Status, Changed Files, Commands,
Build Result, Test Result, Regression Result,
Review, Acceptance, Repair Attempts, Risks,
Technical Debt, Final Diff, Start Commit, End Commit
```

报告 MUST 从持久 Task、Execution、Validation、Review、Audit 和 Git evidence 生成；禁止让模型自由生成无法核对的结果字段。报告中的每个 PASS、文件列表和 commit 必须能回链到 evidence。

## 13. CLI 规范

需求定义的 V1 命令面：

```text
forge init
forge status
forge task new
forge task list
forge task show FORGE-0001
forge run FORGE-0001
forge validate FORGE-0001
forge review FORGE-0001
forge resume FORGE-0001
forge doctor
```

CLI 规则：

- M1 先实现 `init`, `task new`, `task show`，再扩展其余命令。
- 命令 MUST 默认非破坏性；覆盖、删除、迁移必须显式确认或使用明确 flag。
- 人类输出写 stdout，错误和诊断写 stderr。
- 自动化使用的命令 SHOULD 提供稳定的 `--json` 输出；JSON schema MUST versioned。
- `--help` MUST 描述副作用、必需状态和常见修复方式。
- exit code MUST 稳定并文档化：成功、domain/validation failure、usage/config error、blocked、runtime/environment error、internal error 不得混为一类。
- `task show` MUST 从持久状态读取，不从内存缓存猜测。
- 命令完成后 MUST 保证 Task 投影和 audit 一致，或明确返回 recovery instruction。

## 14. Rust 编码规范

除 rustfmt/clippy 外，必须遵守仓库 `AGENTS.md`：

- 能内联时使用 `format!("{value}")`，不得保留 uninlined format args。
- collapse 可合并的 `if`。
- 优先 method reference，避免 redundant closure。
- 避免 `foo(false)`、`bar(None)` 等不透明参数；优先 enum/newtype/named method，必要时使用精确 `/*param_name*/` 注释。
- `match` SHOULD exhaustive，避免 wildcard 吞掉未来状态。
- 新 trait MUST 有职责和实现约束文档。
- trait 异步方法优先原生 RPITIT + 显式 `Send` future；禁止用 `#[async_trait]` 或 `#[allow(async_fn_in_trait)]` 逃避契约。
- 测试优先比较完整对象；使用 `pretty_assertions::assert_eq`。
- expected domain error MUST 使用类型化 error；禁止 panic、字符串匹配和无上下文 `anyhow!` 替代领域分类。
- tracing SHOULD 标注在函数定义，不在调用点随意包 future；先检查下游是否已 instrument。
- 公共 API MUST 最小化；禁止为了测试暴露生产 API。
- 新测试模块使用独立 `*_tests.rs` 和显式 `#[path = "..."]`。

依赖规则：

- 新依赖 MUST 说明为什么标准库或 workspace 现有 crate 不足。
- 修改 `Cargo.toml`/`Cargo.lock` 后 MUST 执行 `just bazel-lock-update` 并提交 `MODULE.bazel.lock`。
- 使用 `include_str!`、`include_bytes!`、`sqlx::migrate!` 等时 MUST 同步 Bazel compile/test data。
- 禁止增加大型数据库、向量数据库或为未来假设引入重量级框架。

## 15. App Server、Hook 与 Extension 规范

- 新 App Server API MUST 使用 v2，不得扩展 v1。
- RPC 名使用单数 `<resource>/<method>`；类型使用 `*Params`, `*Response`, `*Notification`。
- v2 wire 字段和 enum 默认 camelCase；config RPC 保持与 config.toml 一致的 snake_case。
- Optional request field MUST 使用 `Option<T>` 和 `#[ts(optional = nullable)]`；禁止 v2 response 用 `skip_serializing_if` 改变 wire shape。
- Rust/TypeScript rename、tag 和 experimental marker MUST 一致。
- API 变更 MUST 更新 App Server 文档、schema fixture，并运行 `just write-app-server-schema` 和 protocol tests。

扩展选择：

- lifecycle/context/audit 优先 `codex-extension-api` Contributor。
- 阻断或改写工具优先 PreToolUse/PermissionRequest/PostToolUse hooks。
- completion validation 原型优先 Stop hook。
- 只有 Stop hook 的类型、原子性或性能不足被测试证实时，才提案 `CompletionGateContributor`。
- 禁止把 Forge 分支硬编码到 Agent Loop 多个调用点。

## 16. 模型上下文规范

所有模型可见 Forge context MUST：

- 增量构建，禁止重写 ConversationHistory；
- 有稳定 identity/content kind，避免无意义 cache miss；
- 有硬字符/token 上限，单项禁止超过 10K tokens；可能超过 1K tokens 的新 fragment 作为 P0 review；
- 只包含当前 Task 必需事实，不注入整个仓库、完整 audit 或无限 Memory；
- 使用当前 Codex 支持的 `PromptFragment`/`ContextualUserFragment` 机制；新 concrete fragment 必须遵守上游 `core/context` 约束；
- 明确 source、version、freshness 和 truncation；
- 对外部内容标注信任边界，避免把不可信文本当 developer authority。

ForgeMemory 必须经过 Retrieve → Rank → Select → Inject，且注入结果受同样预算约束。

## 17. 安全与 Policy 规范

ForgePolicy 只能收紧，禁止放宽 Codex Sandbox/Approval 的决定。

默认禁止：

- 未审批危险 Shell；
- 无边界递归删除或移动；
- 覆盖 Git 历史；
- 访问项目外敏感目录；
- 执行高风险系统命令；
- 修改 `.git`、凭证、生产数据库或 migration 而无显式授权；
- 把 secret、完整环境变量、token 或敏感 tool payload 写入 audit。

具体要求：

- 命令执行必须保留 cwd、argv/规范化命令、exit code、duration 和 Sandbox/Approval outcome。
- Policy deny MUST fail closed，并提供 rule ID 与非敏感理由。
- 禁止修改 `CODEX_SANDBOX_NETWORK_DISABLED_ENV_VAR` 或 `CODEX_SANDBOX_ENV_VAR` 相关代码。
- 测试不得通过关闭安全策略来获得通过。
- 审计、日志和错误必须执行 allowlist/redaction；默认不记录 process environment。

## 18. Audit、Observability 与隐私规范

AuditEvent 至少包含：

```text
schema_version, event_id, sequence, task_id, type, timestamp,
actor, object_revision, data, evidence_refs, redactions
```

与 Codex 集成后 SHOULD 包含 thread_id、turn_id、tool_call_id 等 correlation ID。

规则：

- audit MUST append-only；投影可以重建，历史事件不能原地改写。
- 每个 Task 创建、状态转换、执行、工具摘要、文件变化、validation、repair、review、acceptance 都 MUST 有事件。
- event ID/sequence MUST 可检测重复、缺口和乱序。
- 大型输出 MUST 外置并记录 hash；敏感内容只记录类别和 redaction marker。
- 记录失败本身不能静默；若 audit 无法可靠持久化，状态变更必须失败或进入可恢复的 degraded state。

## 19. 错误处理与恢复规范

错误至少分为：Config、Schema、NotFound、Conflict、InvalidTransition、PolicyDenied、ApprovalDenied、SandboxDenied、ToolFailure、ValidationFail、ValidationError、Persistence、Corruption、RuntimeUnavailable、Cancelled、BudgetExceeded、Internal。

- 每个错误 MUST 有稳定类别、用户可操作消息和内部 source chain。
- retry 只允许用于明确 transient 且幂等的操作；不得重试 policy deny、invalid transition 或 schema error。
- 中断后 resume MUST 从持久 Task/Execution/Audit 恢复，不依赖进程内对象。
- 发现 corrupt 文件 MUST 保留原文件和诊断，禁止自动覆盖。
- repair、runtime retry 和 validation retry 必须分别计数，不能共享一个模糊 attempts 字段。

## 20. 测试规范

### 20.1 必需测试层

| 层 | 目标 | 必需案例 |
| --- | --- | --- |
| Domain unit | Project/Task/state/schema | 完整对象 equality、合法/非法转换、边界大小、版本 |
| Store integration | 原子写、revision、恢复 | crash residue、并发冲突、损坏文件、symlink/path escape |
| CLI integration | 真实 `forge` binary | init→new→show、幂等、错误输出、exit code、跨进程持久化 |
| App Server integration | 公开 v2 JSON-RPC | thread/turn 关联、通知、resume、未启用 Forge 行为不变 |
| Agent integration | completion/context/tool policy | PASS、FAIL→REPAIR、budget、abort、resume、安全不弱化 |
| Regression | upstream 和 Forge vertical slice | baseline diff、旧 schema、Patch Registry Active patch |

### 20.2 仓库命令

- 禁止直接运行 `cargo test`；使用 `just test`。
- 修改 crate 后运行 `just test -p <package>`。
- common/core/protocol 修改通过 targeted tests 后，完整 `just test` 需要按仓库规则明确批准或交由 CI。
- 代码完成后运行 `just fmt`；大变更运行 `just fix -p <package>`。
- UI/text 输出变化 MUST 有 `insta` snapshot coverage 并人工审查 `.snap.new`。
- 启动 workspace binary 的测试使用 `codex_utils_cargo_bin::cargo_bin`。
- Core Agent 行为变更 MUST 使用 `core/suite` 集成测试；App Server 使用 `TestAppServer` 公共 API 测试。

禁止测试做法：

- 只测试静态常量；
- 删除失败测试以通过 CI；
- 对被删除逻辑增加无意义 negative test；
- 修改全局 process environment 制造难以隔离的测试；
- 仅逐字段断言而不比较完整 domain object；
- 使用 sleep 替代可观察事件同步。

## 21. Quality Gates

每个变更按风险通过以下门：

### Gate A — Scope

- ForgeTask、acceptance 和 owner 明确。
- 没有混入非目标或不相关重构。
- 上游文件修改已登记 Patch。

### Gate B — Design

- 依赖方向正确。
- 复用现有 Codex capability。
- schema、状态、失败和恢复路径已定义。
- 安全与兼容性影响已评估。

### Gate C — Implementation

- format/lint 通过。
- 无 secret、无无界 context、无直接状态写入。
- 公开 API 最小，模块大小合规。

### Gate D — Verification

- build 和 affected tests 通过。
- regression 与 backward compatibility 通过。
- 测试报告和 Git diff 已作为 evidence。

### Gate E — Acceptance

- Review 通过。
- acceptance criteria 逐项有 evidence。
- Audit、Task Report、Patch Registry 和文档同步。

## 22. Git 与 Upstream 规范

- 开发前记录 branch、HEAD、status 和 baseline commit。
- Forge feature 和 upstream sync MUST 使用不同分支/提交。
- 不重写已发布主线历史。
- 任何上游文件修改 MUST 在编码前登记 `UPSTREAM_PATCHES.md`。
- 合并 upstream 时逐项复验 Active patch；上游已有替代时删除 patch。
- 修改依赖、schema、generated file 时必须把对应生成物放在同一 change。
- commit SHOULD 单一职责，能够独立构建和评审。
- 禁止提交凭证、临时运行输出、未审查 snapshot 或大型 build artifact。

## 23. 文档与决策规范

以下变化 MUST 更新文档或 ADR：

- Codex/ForgeOS boundary 或依赖方向；
- `.forge` schema、状态机或 CLI wire/output；
- App Server API、Hook/Extension 使用方式；
- Sandbox/Approval/Policy 行为；
- completion、validation、repair 或 acceptance 语义；
- upstream patch 的新增、替换或删除。

ADR 至少包含 Context、Decision、Alternatives、Consequences、Upstream impact、Migration/rollback。禁止只记录结论而没有被拒绝方案。

## 24. Definition of Done

ForgeTask 只有同时满足以下条件才能进入 `DONE`：

```text
Implementation Completed
AND Build Passed
AND Required Tests Passed
AND Regression Passed
AND Review Passed
AND Acceptance Passed
```

此外，交付 change 必须满足：

- Task 状态和 audit 一致且可恢复；
- changed files、commands、start/end commit、final diff 已记录；
- 没有未登记的 upstream patch；
- license/NOTICE 和 attribution 未被破坏；
- 文档、schema、fixture、generated files 与代码一致；
- 已知风险、技术债和未执行检查被明确披露；
- “未执行”不得写成 “通过”，“Agent 声称通过”不得替代验证证据。

## 25. Code Review Checklist

评审者必须逐项确认：

- [ ] 变更属于明确 ForgeTask，scope 和 acceptance 一致。
- [ ] 没有重新实现 Codex Owned 能力。
- [ ] 依赖方向和模块所有权正确。
- [ ] 状态只由 TaskStateMachine 修改。
- [ ] 持久写入原子、versioned、并发安全、可恢复。
- [ ] 路径 canonicalization、symlink 和 workspace boundary 已处理。
- [ ] ForgePolicy 没有放宽 Sandbox/Approval。
- [ ] context bounded、stable、incremental、来源清晰。
- [ ] error 分类、取消、超时和 retry 语义清晰。
- [ ] Audit 已脱敏，未记录 secret 或无界输出。
- [ ] 测试覆盖主要行为和失败路径，未删除现有测试。
- [ ] API/schema/CLI backward compatibility 已评估。
- [ ] 上游改动已登记，patch 足够窄且有移除条件。
- [ ] Build/Test/Regression/Review/Acceptance evidence 完整。
