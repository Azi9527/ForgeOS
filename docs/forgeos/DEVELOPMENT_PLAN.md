# ForgeOS Detailed Development Plan

## 1. 计划目标

本计划把 M0 架构结论转换为可执行的 V1 开发序列。最终目标是完成一个真实 Feature Vertical Slice：

```text
forge task new
→ ForgeTask + Context + Rules
→ forge run FORGE-0001
→ Codex Analyze / Plan / Implement
→ Build / Test / Regression
→ Review / Acceptance
→ FAIL 时 Repair / Revalidate
→ Forge Task Report
→ DONE
```

本计划以依赖和质量门排序，不承诺未经团队容量评估的日历日期。每个 work package 必须满足 [DEVELOPMENT_STANDARDS.md](DEVELOPMENT_STANDARDS.md)。

## 2. 当前起点

### 2026-08-24 SDK-first 决策

ForgeOS 不再把 WSL、全量 Rust workspace 构建或自研 App Server client 作为开始开发的前置条件。当前首先使用官方 Python SDK 建立持续、多轮 Codex 集成；CLI 只承担单次管理、诊断和兼容任务。只有需要修改上游 Rust 源码时，才针对该 patch 建立对应的 upstream build/test baseline。

### 已完成

- 官方 Codex 当前源码已 shallow clone，基线 commit 为 `068c49f075cf287a1fe7d1ee36cf005efac922e7`。
- `upstream` 已指向 `https://github.com/openai/codex.git`。
- M0 架构、执行链、扩展点、边界、许可证和 upstream 策略已完成。
- 已确认 TUI/exec 汇聚 App Server，现有 Hook/Extension API 可承担大多数 Forge 集成。
- 已确认 Stop hook 是第一版 Validation completion gate 的最佳入口。
- 已新增独立 `forgeos/` Python package 和 `CodexSdkGateway`，支持 Thread start/resume、Turn run、结构化运行证据、指定 Codex binary 和安全默认值。
- 已实现 ForgeProject、ForgeConfig、ForgeTask、状态机、`.forge/` 原子持久化、Audit、Validation、Review/Acceptance gate 和同线程 Repair。
- 已实现薄管理 CLI：`forge init/status/task new/show/list`；多轮运行仍只通过 Python service/SDK。
- 48 项隔离测试、Ruff lint/format、真实 Codex Python SDK 模型回合和本地浏览器控制链全部通过。

### 未完成 / 阻塞

- `origin` 尚未配置，因为没有 ForgeOS repository URL。
- checkout 是 shallow clone，尚未建立完整 upstream 历史。
- 官方 Rust Build、Format、Test、Lint baseline 尚未执行；当前没有修改 Rust/upstream 文件，因此它不是 Python SDK 集成的阻塞项。

当前开发直接沿 Python SDK 集成纵向切片推进。Rust baseline 在出现首个上游 patch 提案时按 patch 范围执行，不再安装独立大型虚拟机作为默认步骤。

## 3. 交付分解

```text
S0 Python SDK Integration
  ↓
M1 Forge Foundation
  ↓
M2 Execution & Codex Integration
  ↓
M3 Validation / Regression / Repair
  ↓
M4 Review & File-backed Engineering Intelligence
  ↓
V1 Vertical Slice & Release Gate
```

复杂 Multi-Agent、Model Router、Web UI、SaaS、向量数据库和分布式执行进入 V1 之后的 backlog，不得进入上述 critical path。

### 3.1 当前目标模式实施看板

本看板是当前开发顺序的权威入口；后文保留详细需求分解，但不得重新引入 WSL-first、Rust-workspace-first 或 CLI-first 路线。

| Gate | 交付物 | 验收 | 状态 |
| --- | --- | --- | --- |
| S0 SDK Boundary | `CodexSdkGateway`、安全默认值、start/resume/run、结构化结果 | isolated tests；现有 Codex binary App Server initialize smoke | Complete |
| S1 Domain | ForgeProject、ForgeConfig、ForgeTask、TaskStateMachine、evidence types | round-trip；完整合法转换；非法转换 fail closed | Complete |
| S2 Persistence | `.forge/` layout、原子 JSON/YAML-compatible 文件、Task repository、Audit JSONL | init 幂等；不覆盖冲突；revision check；重启恢复 | Complete |
| S3 Execution | ForgeTask ↔ Codex thread/turn correlation、execution record、resume | fake SDK 多轮测试；Codex completion 不写 DONE | Complete |
| S4 Validation | 无 shell 的 argv checks、timeout、bounded output、Validation report | pass/fail/timeout；失败进入 REPAIRING；证据持久化 | Complete |
| S5 Review/Acceptance | review evidence、human/system acceptance、DONE gate | validation + review + acceptance 缺一不可 | Complete |
| S6 Verification | unit/integration/security tests、package compile、真实 SDK smoke | 全部 PASS；真实模型 turn 为显式 opt-in；upstream patch 为 0 | Complete |

### 3.2 V1 可运行纵向切片

```text
ForgeService.init_project
  → .forge/forge.yaml
ForgeService.create_task
  → FORGE-0001 + audit
ForgeExecutionService.run_task
  → Python SDK thread/start or thread/resume
  → Codex TurnResult + correlation + execution evidence
  → VALIDATING
ValidationRunner
  ├─ FAIL → REPAIRING → same Codex thread → VALIDATING
  └─ PASS → REVIEWING → ACCEPTING → DONE
```

完成条件：

- 所有工程状态由 ForgeOS service/state machine 写入，SDK 和 Agent 只能提供 evidence。
- 默认 `ApprovalMode.deny_all`；V1 不实现自动放宽权限。
- Validation command 使用 argv 数组和 `shell=False`，有 timeout 和输出硬上限。
- 文件写入保持在 canonical project root 下，拒绝 symlink/path traversal。
- 测试默认不调用模型；真实 SDK 模型验证必须显式启用。本轮已在只读、`deny_all`、临时线程配置下显式执行并通过。

### 3.3 当前纵向切片验证结果

| Gate | 命令/证据 | 结果 |
| --- | --- | --- |
| Unit/Integration/Security | `cd forgeos && python -m pytest` | PASS，40 passed，0 skipped |
| Lint | `ruff check --no-cache .` | PASS |
| Format | `ruff format --no-cache --check .` | PASS，19 files formatted |
| Official SDK import | 仓库 `sdk/python/src` + 本机 Codex 0.146.1 binary | PASS |
| Real model turn | read-only workspace + `deny_all` + ephemeral thread | PASS，`completed`，响应 `FORGEOS_SDK_SMOKE_OK` |
| Upstream patch | `git status` 与 Patch Registry | 0；未修改 Codex-owned 文件 |

完整证据与已知边界见 [VALIDATION_REPORT.md](VALIDATION_REPORT.md)。

### 3.4 UI Developer Preview（2026-08-24）

状态：**Complete**。

| Gate | 交付物 | 验收 | 状态 |
| --- | --- | --- | --- |
| UI-01 Control API | Project/Task/Job/Audit/Execution/Validation JSON projection | service tests；所有 mutation 复用领域门禁 | Complete |
| UI-02 Background Jobs | 每 Task 单活动作业、串行 mutation、bounded error/history | 并发重复 run 被拒绝；成功/失败可查询 | Complete |
| UI-03 Local HTTP | 标准库 loopback server、session token、CSP、body cap | 未授权 403；非 loopback fail closed | Complete |
| UI-04 Web UI | 初始化、Task 列表/详情、创建、Run/Validate/Review/Accept、活动时间线 | 真实浏览器交互与视觉检查通过 | Complete |
| UI-05 Packaging | `forge ui`、wheel static assets | wheel 包含 HTML/CSS/JS/control modules | Complete |
| UI-06 Real Chain | Control Job → official Python SDK → Validation | `SUCCEEDED`；任务停在 `REVIEWING` | Complete |

UI 保持薄控制面，不拥有状态转换逻辑。API 请求不能直接写 Task status；Run、Validation、Review、Acceptance 分别调用现有 Execution/Workflow/Forge service。界面架构、安全模型和 API 见 [UI_DEVELOPER_PREVIEW.md](UI_DEVELOPER_PREVIEW.md)。

### 3.5 下一阶段：N1 Controlled Execution & Engineering Evidence

状态：**Complete（2026-08-24）**。

当前最小纵向切片已经证明 SDK → Validation → Review → Acceptance 边界成立；下一阶段不扩张 Agent Runtime 或 Web Console，而是补齐运行控制与工程证据：

```text
TurnHandle stream / interrupt / steer / resume
→ persistent ExecutionAttempt / ExecutionStep
→ Git baseline / current evidence
→ deterministic Rules
→ bounded Context Package
→ Doctor + thin UI projection
```

N1 的 10 个工作包、C18–C25 已全部交付，upstream patch 为 0。完成范围包括持久 ExecutionAttempt/Step、SDK stream/interrupt/steer/resume、Git evidence、Rules、bounded Context Package、Doctor 及 Control API/UI。权威范围与设计见 [NEXT_STAGE_PLAN.md](NEXT_STAGE_PLAN.md)，实测证据见 [N1_VALIDATION_REPORT.md](N1_VALIDATION_REPORT.md)。当前开发入口转为 N2：typed L1-L5 Validation、Regression、criteria Acceptance 和 Task Report。

### 3.6 N2 Validation & Report Completion

状态：**Complete（2026-08-24）**。

N2 已交付 typed L1–L5 协议、不可变 pre-execution baseline、L4 regression 分类、六维 Review、逐条 L5 Acceptance、DONE Task Report gate，以及 Workflow/API/CLI/UI 和完整失败→修复→DONE 测试。设计与迁移策略见 [N2_DEVELOPMENT_PLAN.md](N2_DEVELOPMENT_PLAN.md)，实测证据见 [N2_VALIDATION_REPORT.md](N2_VALIDATION_REPORT.md)。upstream patch 为 0。

## 4. 工作包约定

| 字段 | 含义 |
| --- | --- |
| ID | 稳定任务编号，便于 commit、audit 和验收引用。 |
| Depends | 必须先通过的工作包或 Gate。 |
| Deliverables | 预期代码、schema、fixture、文档或报告。 |
| Acceptance | 可观察、可执行的完成条件。 |
| Risk | Low/Medium/High；High 必须有 design review。 |
| Size | S/M/L，是相对复杂度，不是工期。 |

每个代码 change SHOULD 少于 800 changed lines；复杂逻辑 SHOULD 少于 500 changed lines。超出时必须拆成可独立构建和测试的阶段。

## 5. G0 — Conditional Upstream Baseline Gate

### 目标

仅当计划修改 Codex 上游 Rust 文件时，针对受影响 crate 建立可重复基线。纯 Python ForgeOS 代码不需要先构建整个 Codex workspace。

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| G0-01 | Upstream patch proposal | 记录将修改的 crate、调用链和现有测试 | patch scope 与测试范围明确；不能用全量构建代替范围分析 | Low / S |
| G0-02 | G0-01 | 在已有受支持环境或 CI 中运行受影响 crate 的官方 baseline | 修改前 build/test 有真实结果和 commit | Medium / M |
| G0-03 | G0-02 | 修改后运行相同 targeted checks；公共 core/protocol 变更按 AGENTS.md 扩大测试 | before/after 可比较；失败查根因 | Medium / M |
| G0-04 | Explicit need | 只有目标测试确实要求时才准备额外 OS/工具链环境 | 记录必要性、磁盘成本和清理方式；需要系统变更时先获授权 | Medium / M |
| G0-05 | Repository URL | 配置 `origin`；按需 `git fetch --unshallow upstream` | remote 拓扑正确；`main` 跟踪策略明确；merge-base 可计算 | Low / S |
| G0-06 | G0-04 | 固化 `BASELINE_REPORT`：OS、toolchain、commit、commands、known failures | 报告可由另一环境复现，未执行项明确 | Low / S |

建议命令以仓库文档为准：

```text
cd codex-rs
cargo build
cargo run --bin codex -- --version
just fmt-check
just clippy
just test -p codex-tui
just test
```

### G0 Exit Gate

- 仅对实际将修改的 upstream scope 建立 baseline。
- target build/test 在同一环境、同一命令下可比较。
- 所有 baseline failure 已分类为 environment、upstream existing 或 source regression。
- 无关 crate 和全量虚拟机不进入默认开发路径。

## 6. M1 — Forge Foundation

### 6.1 目标和边界

M1 以 Python service/library 为主，实现 ForgeProject、ForgeConfig、ForgeTask、TaskStateMachine、`.forge/` protocol 和 Audit skeleton。CLI 只提供单次管理命令；持续执行由 SDK gateway/service 持有。M1 不实现 Validation runner、不增加 Memory engine。

M1 第一条可演示链路：

```text
forge init
→ .forge/ + forge.yaml
forge task new
→ FORGE-0001
forge task show FORGE-0001
→ persisted task + status + audit references
```

### 6.2 M1-A — Workspace and Domain Skeleton

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M1-01 | S0 | 在现有 `forgeos/` package 新增 domain/service skeleton | pytest/compile 独立通过；不修改 Cargo/Bazel；未依赖 `codex-core` | Low / S |
| M1-02 | M1-01 | `ForgeError` 分类、schema version、domain ID/value object 和 Python public API | public API 最小；错误可比较、可序列化为诊断 | Low / M |
| M1-03 | M1-02 | ForgeProject domain：id/name/root/language/framework/repository/default branch | root canonicalization 和 workspace boundary 测试；完整对象 round-trip | Medium / M |
| M1-04 | M1-02 | ForgeConfig schema 和 loader；实现需求中的 forge/project/runtime/task/execution/validation/git/audit | valid fixture round-trip；unknown major/invalid path fail closed；错误含字段路径 | Medium / M |

### 6.3 M1-B — File Protocol and Store

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M1-05 | M1-03, M1-04 | 私有 ForgeStore abstraction：canonical paths、atomic temp+rename、revision check | 不原地截断；并发 revision 冲突可检测；临时文件可恢复 | High / L |
| M1-06 | M1-05 | `.forge/` layout builder 和 deterministic templates | 目录与需求一致；内容 UTF-8/LF；输出确定性 | Medium / M |
| M1-07 | M1-06 | `forge init` 命令 | 空项目成功；重复执行幂等；现有冲突文件不覆盖；project root 外拒绝 | High / M |
| M1-08 | M1-05 | schema migration contract 和 fixtures；V1 先实现 identity migration | 当前版本可读；未知未来版本拒绝；migration retry 不破坏数据 | Medium / M |

M1-05 必测故障：

- 写到 temp 后崩溃；
- rename 前/后崩溃；
- revision 已变化；
- 只读目录；
- symlink 指向项目外；
- corrupt YAML/JSONL；
- Windows 与 Unix path separator；
- 同时创建 Task ID。

### 6.4 M1-C — ForgeTask and State Machine

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M1-09 | M1-02 | ForgeTask 字段、TaskType、priority/risk、acceptance criteria、revision/timestamps | 六种 type 支持；字段有硬上限；完整对象 equality/round-trip | Medium / M |
| M1-10 | M1-09 | TaskStateMachine 正常路径、repair 路径和异常状态转换表 | 所有合法边有测试；非法边在写盘前拒绝；无 wildcard match | High / M |
| M1-11 | M1-05, M1-09 | 并发安全 Task ID allocator 和 active/completed/failed repository | 首个 ID `FORGE-0001`；并发不重复；重启后单调 | High / M |
| M1-12 | M1-10, M1-11 | Transition service：expected revision、actor、reason、evidence prerequisites | 状态投影与 audit 同步；冲突无部分写入；Agent actor 不能直接 DONE | High / L |

M1 状态机必须精确实现：

```text
CREATED → ANALYZING → PLANNED → IMPLEMENTING → VALIDATING
→ REVIEWING → ACCEPTING → DONE

VALIDATING → REPAIRING → VALIDATING

Exceptional: BLOCKED / FAILED / CANCELLED
```

### 6.5 M1-D — Audit Skeleton and CLI

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M1-13 | M1-05 | AuditEvent envelope、JSONL append、sequence/event ID、redaction | append-only；重复/缺口可检测；secret fixture 被脱敏 | High / M |
| M1-14 | M1-11, M1-13 | `task new` service + 单次 CLI adapter：输入、持久化和事件 | 创建 FORGE-0001；失败无孤立文件；service API 稳定 | Medium / M |
| M1-15 | M1-14 | `forge task show` 和 machine-readable `--json` | 跨进程读取一致；损坏/不存在可诊断；JSON versioned | Low / M |
| M1-16 | M1-14 | `forge task list` 和 `forge status` 的最小实现 | 排序确定；active/completed/failed 可区分；不依赖内存 cache | Low / M |
| M1-17 | M1-07, M1-15 | `forge doctor` 检查 config、layout、Git、Codex/runtime prerequisites | 每项输出 PASS/WARN/FAIL；不改变工程；不泄露环境 secret | Medium / M |

### 6.6 M1-E — Verification and Documentation

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M1-18 | M1-07, M1-14, M1-15 | service integration + 薄 CLI boundary tests | `init→new→show`、幂等、冲突、重启全部通过；多轮 SDK 不依赖 CLI | Medium / M |
| M1-19 | M1-18 | Linux/macOS/Windows path、atomic write 和 serialization matrix | 平台测试通过；OS-specific 行为有显式封装 | Medium / L |
| M1-20 | All M1 | `.forge` protocol、CLI reference、migration 和 recovery runbook | 文档/schema/fixture 一致；从空仓库可重现 | Low / M |
| M1-21 | All M1 | Python format/lint/compile/pytest、license review、Patch Registry update | 所有 M1 Quality Gates PASS；无 upstream 改动 | Low / M |

### M1 Exit Gate

- `forge init`, `task new`, `task show` 可运行。
- ForgeProject/Config/Task/StateMachine 有完整测试。
- 文件写入原子、并发安全、versioned、可恢复。
- Audit append-only 且脱敏。
- Codex 未启用 Forge 时没有行为变化。
- 没有修改 Codex Agent Loop/Sandbox/Approval/MCP/Context Runtime。
- Cargo/Bazel workspace 未修改；Upstream Patch Registry 仍为零 Active patch。

## 7. M2 — Execution & Codex Integration

### 7.1 目标

实现 ForgeWorkflow、ForgeExecution、ExecutionStep、Task→Codex Runtime、Context/Rules 注入和执行 Audit。仍不让 Agent completion 等同 Task completion。

### 7.2 工作包

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M2-01 | M1 | Workflow schema：feature/fix/refactor/review、step 和 transition | 四种 workflow fixture；未知 step/version 拒绝；默认流程与需求一致 | Medium / M |
| M2-02 | M2-01 | ForgeExecution/ExecutionStepResult persistence | 每步记录 input/output/files/commands/error；中断可 resume | High / L |
| M2-03 | M1 | Git awareness service：branch/status/diff/commit、baseline/final diff | Task 开始记录 HEAD/status；项目外 repo 和 dirty tree 有明确 policy | High / M |
| M2-04 | S0 | 扩展现有 Python `CodexSdkGateway`：stream/steer/interrupt、错误分类和 audit event | 只用官方 SDK 公共 API；start/resume/run 已完成，新增能力有 fake SDK 合约测试 | Medium / M |
| M2-05 | M2-04 | ForgeTask ↔ Codex thread/turn correlation persistence | 多 turn 可关联一个 Task；resume 后关联不丢失 | High / M |
| M2-06 | M1, M2-04 | SDK developer instructions/context package adapter | bounded、stable、来源/版本/truncation 可见；无 history rewrite | Medium / M |
| M2-07 | Verified SDK gap | 评估原始 App Server/Extension API 是否确有必要；无证据则不实施 | gap、替代方案、patch 和 targeted baseline 全部书面化 | High / S |
| M2-08 | M2-04 | SDK Thread/Turn/Item/Token audit adapter | correlation 完整；payload allowlist/redaction；取消/失败被记录 | High / L |
| M2-09 | M2-04 | ForgePolicy 映射到 SDK approval mode；默认 `deny_all` | 只能收紧 Codex policy；任何放宽有 rule/evidence；安全 regression 通过 | High / M |
| M2-10 | M2-02, M2-04, M2-05 | `forge run` 和 `forge resume` orchestration | 状态转换正确；Codex error 不写 DONE；进程重启可 resume | High / L |
| M2-11 | All M2 | Python SDK execution integration suite | start/turn/interrupt/resume/disabled-mode 全部通过；真实模型测试显式 opt-in | High / L |

### M2 Exit Gate

- `forge run FORGE-0001` 能建立 Codex Thread/Turn 并记录 ExecutionStep。
- Context/Rules 有界注入，模型能看到 Task acceptance，但不获得状态写权限。
- Git baseline、commands、files changed 和 Codex correlation 可审计。
- 中断后 `forge resume` 从持久状态恢复。
- ForgePolicy 未弱化 Sandbox/Approval。
- 没有修改 Agent completion 语义。

## 8. M3 — Validation, Regression and Repair

### 8.1 目标

把“Agent 完成”变成“等待独立验证”，并实现 Build/Test/Regression/Acceptance、失败修复和预算控制。

### 8.2 工作包

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M3-01 | M1, M2-02 | ValidationPlan、ValidationResult、Evidence schema | L1-L5 和 PASS/FAIL/SKIP/ERROR 精确表达；输出有界 | Medium / M |
| M3-02 | M3-01 | Validation config loader：build/test/regression/acceptance | required validators、cwd、timeout、environment policy 可验证 | High / M |
| M3-03 | M2-03, M3-02 | Governed command runner adapter，复用 Codex/host execution boundary | command/cwd/approval/sandbox/exit/duration evidence 完整 | High / L |
| M3-04 | M3-03 | Build、unit、integration validator | 成功/失败/timeout/cancel/infra error 正确分类 | High / L |
| M3-05 | M2-03, M3-04 | Regression evaluator：baseline vs current checks/diff | 新 failure 与已有 baseline failure 可区分；不得用 baseline 掩盖回归 | High / L |
| M3-06 | M3-01 | Acceptance evaluator：criteria-by-criteria evidence | 每条 acceptance 有 PASS/FAIL/evidence；required SKIP 不通过 | High / M |
| M3-07 | M2-06, M3-04 | Stop hook completion gate prototype | Codex Turn terminal 前运行；PASS allow，FAIL block + bounded continuation | High / L |
| M3-08 | M3-07 | Repair loop、Failure Context 和独立 repair/validation budget | 默认最多 3 次；耗尽进入 BLOCKED；取消和 resume 正确 | High / L |
| M3-09 | M3-04, M3-06 | `forge validate` 命令和 VALIDATING transition | Agent claim 不影响结果；重复验证产生新 evidence，不覆盖旧记录 | Medium / M |
| M3-10 | M3-05, M3-06, M3-08 | Validation/repair regression suite | PASS、FAIL→REPAIR→PASS、3次失败、ERROR、abort、resume 全覆盖 | High / L |
| M3-11 | All M3 | 评估 Stop hook 局限，形成“无需 patch”或 FUP-0003 design proposal | 没有实证不足时不得修改 `session/turn.rs` | High / M |

### Completion Gate 决策门

只有以下任一情况被基准/测试证实时，才允许将 FUP-0003 从 Proposed 变为 Active：

- 外部 Stop hook 无法保证状态与终态事件的原子顺序；
- 所需强类型 scoped state 无法安全传递；
- 外部进程开销对普通 Turn 产生不可接受延迟；
- resume/cancellation 语义无法通过现有 hook 正确实现。

即使激活，也只允许增加窄化 `CompletionGateContributor`，调用点与现有 Stop hook 相邻；禁止通用 Forge middleware 侵入 Agent Loop。

### M3 Exit Gate

- `forge validate` 能执行 required checks 并生成 evidence。
- Agent final response 无法绕过 Validation。
- FAIL 自动进入 REPAIRING，重试受预算限制。
- Regression 和 Acceptance 独立于测试命令结果。
- required SKIP/ERROR 不能进入 DONE。
- PASS/FAIL/abort/resume/upstream-disabled regression 全通过。

## 9. M4 — Review & File-backed Engineering Intelligence

### 9.1 目标和边界

实现最小 Review、Decision/Failure/Pattern Memory 和 Task Report。V1 Memory 是经过接受、文件化、可追溯的工程知识，不是向量数据库、RAG 平台或无限 Prompt 注入。

### 9.2 工作包

| ID | Depends | Scope / Deliverables | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- |
| M4-01 | M3 | ForgeReview schema/checklist：architecture/quality/risk/tests/compat/debt | Review 与 Validation 类型分离；每项有结论和 evidence | Medium / M |
| M4-02 | M4-01 | `forge review` orchestration，可复用 Codex Review 产出候选 | Codex review 不能自行批准；授权 policy 决定 REVIEWING→ACCEPTING | High / L |
| M4-03 | M1 store | Decision/Failure/Pattern file schema、source/version/freshness/acceptance | 未接受 candidate 不可注入；失效/替代链可追踪 | Medium / M |
| M4-04 | M4-03, M2-07 | Retrieve→Rank→Select→Inject 的无向量最小实现 | 规则确定性、budget bounded、source visible；完整 memory 不全量注入 | High / L |
| M4-05 | M3, M4-02 | Acceptance service 和 ACCEPTING→DONE gate | 六项 DoD evidence 齐备才 DONE；actor/policy 可审计 | High / M |
| M4-06 | M2-03, M3, M4-02 | Forge Task Report generator | 包含需求规定的 Task、changed files、commands、validation、review、risk、diff、commits | Medium / M |
| M4-07 | All M4 | Memory/review/acceptance regression suite | stale memory、unaccepted memory、review fail、missing evidence 均阻断 | High / L |

### M4 Exit Gate

- Review 与 Validation 语义分离。
- Memory 只有 accepted records 可进入 Context Package。
- Acceptance 是进入 DONE 的唯一门。
- Task Report 可从持久文件、Git 和 Audit 重建。
- 不依赖数据库、embedding 或外部 RAG 服务。

## 10. V1 Vertical Slice

### 10.1 场景

使用隔离 fixture repository 执行需求示例“增加用户导出 Excel 功能”，或选择同等复杂度、能稳定自动验证的 feature。禁止直接把主 ForgeOS 仓库作为破坏性演示目标。

### 10.2 流程

1. `forge init` 创建项目协议。
2. `forge task new` 创建 FEATURE Task 和 acceptance criteria。
3. `forge run` 记录 Git baseline，构建 Context/Rules 并启动 Codex。
4. Codex 分析、规划、修改和调用工具。
5. Stop gate 运行 Build/Test/Regression/Acceptance。
6. 首次场景应包含一个可控 validation failure，验证 Repair Loop。
7. Review 检查架构、质量、风险、测试、兼容性、技术债。
8. Acceptance evidence 齐备后进入 DONE。
9. 生成 Forge Task Report 和 Final Diff。
10. 删除进程内状态后，从 `.forge/` + Git + Audit 重建报告，验证可恢复性。

### 10.3 Vertical Slice Acceptance

- 一个真实 Feature 从 CREATED 到 DONE。
- 至少经历一次 VALIDATING→REPAIRING→VALIDATING。
- Agent 无法直接修改 Task status 或伪造 PASS。
- start commit、end commit、changed files、commands、repair attempts 完整。
- Task Report 与 Git/evidence 一致。
- 重启/resume 后不丢状态。
- Forge disabled 的 Codex baseline 行为不变。

## 11. 测试与验证矩阵

| 能力 | Unit | Store/CLI | App Server | Agent E2E | Cross-platform |
| --- | --- | --- | --- | --- | --- |
| Config/Project | Required | Required | N/A | N/A | Required |
| Task/State | Required | Required | N/A | Indirect | Required |
| Atomic store/Audit | Required | Required | N/A | Recovery | Required |
| Workflow/Execution | Required | Required | Required | Required | Required |
| Context/Rules | Budget/unit | Fixture | Required | Required | Required |
| Tool Policy | Rule tests | N/A | Required | Security regression | Platform sandbox matrix |
| Validation/Repair | Required | Required | Required | Required | Required |
| Review/Acceptance | Required | Required | Optional | Required | Required |
| Memory | Required | Required | Optional | Context regression | Required |

每个里程碑至少保留：

- command log；
- build/test/lint result；
- failing test root-cause；
- Git diff/stat；
- schema fixture changes；
- active upstream patch verification；
- known unexecuted checks。

## 12. 推荐 Change / PR 序列

为降低冲突和评审成本，建议按以下顺序落地：

| Change | 内容 | 上游文件预算 |
| --- | --- | --- |
| C01 | Workspace/Bazel scaffold + FUP-0001 | 仅 manifest/lock/build |
| C02 | Domain IDs、errors、ForgeProject、ForgeConfig | 0 个 Codex runtime 文件 |
| C03 | ForgeStore atomic/revision/path safety | 0 |
| C04 | `.forge` layout + `forge init` | 0 |
| C05 | ForgeTask + TaskStateMachine | 0 |
| C06 | Task allocator/repository + `task new/show` | 0 |
| C07 | Audit skeleton + list/status/doctor | 0 |
| C08 | M1 integration/platform tests and docs | 0 |
| C09 | Workflow/Execution/Git baseline | 0 |
| C10 | App Server adapter + correlation | 尽量 0 |
| C11 | Forge extension + FUP-0002 composition | 1 个窄 composition patch |
| C12 | Context/Rules/Audit/Policy contributors | 0 个 core patch |
| C13 | Validation runner + CLI | 0 |
| C14 | Stop hook repair loop | 0 个 core patch |
| C15 | Review/Acceptance/Task Report | 0 |
| C16 | Minimal accepted Memory | 0 |
| C17 | Vertical slice/release hardening | 0；复验所有 Active patch |

每个 change 必须可独立 build/test。不得把 C01–C08 合并成一个大型 “M1 implementation” change。

## 13. Release Gates

### V1 Alpha

- M1 Exit Gate 通过。
- `.forge` schema 标记 alpha，migration contract 已建立。
- CLI 人类输出可变，但 JSON schema versioned。

### V1 Beta

- M2/M3 Exit Gate 通过。
- completion gate、repair、resume 和安全 regression 稳定。
- upstream sync 至少演练一次。

### V1 Release Candidate

- M4 和 Vertical Slice 通过。
- Cross-platform matrix 完成。
- License/NOTICE/SBOM review 完成。
- 所有 Active upstream patch 逐项复验。
- 没有 P0/P1 open defect；P2 必须有明确接受决定和 workaround。

### V1 General Availability

- 从干净 clone 可按文档构建和运行。
- schema migration、backup/recovery 和 upstream sync runbook 已演练。
- Task Report 和 audit 满足可追踪性要求。
- Release artifact 包含 LICENSE、NOTICE 和第三方 attribution。

## 14. 风险登记

| Risk ID | 风险 | Probability / Impact | Mitigation | Trigger |
| --- | --- | --- | --- | --- |
| R-01 | 当前环境不能构建 Rust | High / High | G0 独立 Gate，不在未验证环境开始 M1 | Rust/Just/nextest 不可用 |
| R-02 | Workspace/Bazel/lock 与 upstream 高频冲突 | Medium / Medium | FUP-0001、最少新依赖、同步演练 | manifest merge conflict |
| R-03 | Forge domain 反向污染 `codex-core` | Medium / High | dependency test/review；App Server composition | core imports Forge type |
| R-04 | Stop hook 无法满足 completion 原子性 | Medium / High | M3 prototype + decision gate；窄 typed gate 备用 | terminal event 早于 evidence commit |
| R-05 | `.forge` 并发或崩溃导致状态损坏 | Medium / High | atomic write、revision、lock、recovery suite | partial/corrupt projection |
| R-06 | Agent claim 被误当 PASS/DONE | Medium / Critical | evidence-only validation；TaskStateMachine authority | status handler读取模型文本 |
| R-07 | Context 无界导致延迟/cache miss | Medium / High | hard budget、stable fragments、metrics | fragment >1K/P0 或频繁变化 |
| R-08 | Audit 泄露 secret | Medium / Critical | allowlist/redaction、security fixtures、外置 hash | token/env/tool payload 出现在 logs |
| R-09 | ForgePolicy 弱化 Codex security | Low / Critical | monotonic policy tests；deny precedence | Forge allow 覆盖 Codex deny |
| R-10 | M1 过度拆 crate/抽象 | Medium / Medium | store/audit 先私有模块；按真实复用拆分 | 新 crate 无独立 consumer |
| R-11 | Upstream Project/Memory API 变化 | High / Medium | 不作为 V1 权威；adapter 隔离实验 API | protocol experimental change |
| R-12 | V1 scope creep 到 UI/Multi-Agent/Router | Medium / High | non-goal gate；backlog 隔离 | Task 无法映射 M1–M4 acceptance |

## 15. Definition of Ready

一个开发工作包只有满足以下条件才能进入 IMPLEMENTING：

- objective、scope、non-scope、acceptance 明确；
- 依赖 work package 已通过；
- 目标源码和测试已阅读；
- 预计文件和 owner 已列出；
- schema/API/security/upstream 影响已评估；
- test plan、failure/recovery plan 已写明；
- High risk 任务完成 design review；
- 必需系统权限、凭证或外部环境已准备，且不要求开发者绕过安全边界。

## 16. Definition of Done

一个工作包完成必须满足：

- Deliverables 全部存在且 scope 内无隐藏 TODO；
- acceptance criteria 有可验证 evidence；
- format、build、affected tests、lint 和 regression 通过；
- schema/fixture/generated file/文档同步；
- errors、cancel、timeout、resume 和 recovery 已覆盖到相称风险；
- Audit 无 secret，Git diff 无无关变更；
- 上游 patch 已登记并包含 removal condition；
- Review 通过；未执行检查和 residual risk 明确记录。

ForgeTask `DONE` 还必须满足 Implementation、Build、Required Tests、Regression、Review、Acceptance 六项全部 PASS。

## 17. 首个可执行开发批次

G0 关闭后，按以下顺序开始，不并行修改高冲突 workspace 文件：

1. 创建 M1 Foundation ForgeTask，固定 acceptance 和 patch budget。
2. 激活 FUP-0001，新增两个空 crate 和 build targets。
3. 只实现 error/ID/schema version/ForgeProject/ForgeConfig。
4. 通过 domain tests 后实现原子 ForgeStore。
5. 通过 crash/concurrency/path tests 后实现 `forge init`。
6. 实现 ForgeTask 和完整状态转换表。
7. 实现 allocator、repository、`task new/show`。
8. 增加 Audit、CLI integration tests 和 recovery documentation。
9. 运行 M1 Quality Gates；不通过不得开始 M2 App Server integration。

该批次的可见验收命令：

```text
forge init
forge task new --type FEATURE --title "Example"
forge task show FORGE-0001
forge doctor
```
