# ForgeOS V1 Roadmap

## 1. 范围原则

V1 只建立单 Agent 软件工程闭环。Codex 继续拥有 Agent Runtime；ForgeOS 建立 Project/Task/Rules/Workflow/Validation/Review/Audit 的可执行协议。

明确不进入：Memory 平台化、复杂 Multi-Agent、Model Router、Web UI、向量数据库、大型数据库、分布式队列、SaaS/IAM/Billing。M4 只实现经过接受、文件化、可追溯的最小 ForgeMemory，不实现向量检索或 RAG 平台。

## 2. M0 — Architecture Mapping

状态：**架构文档完成；可执行基线受环境阻塞**。

已完成：

- 当前 Codex 源码和 commit 确认；`upstream` remote 配置。
- 需求、README、AGENTS、CONTRIBUTING、LICENSE、NOTICE、安装/构建规则阅读。
- CLI→App Server→Thread/Session→Agent Loop→Tools→Completion 真实调用链。
- Context、Sandbox、Approval、Persistence、Config、SDK、Hooks/Extension API 映射。
- Forge/Codex 边界、集成架构、Patch Registry 和上游策略。

Rust build/format/test baseline 改为条件 Gate：只有实际提案修改某个 upstream Rust crate 时，才在已有受支持环境或 CI 中先跑该范围的真实 baseline。Python SDK 集成不被全量 Rust workspace 构建阻塞。

## 3. M1 — Foundation

在 M1 前先完成 S0 Python SDK Integration。S0 已交付 `forgeos/` package、`CodexSdkGateway`、持久 Thread start/resume、Turn run、结构化结果、安全默认值和隔离测试。M1 只交付 ForgeProject、ForgeConfig、ForgeTask、TaskStateMachine、`.forge` protocol、单次管理 CLI 和 Audit skeleton。

当前状态（2026-08-25）：M1 foundation、N1 Controlled Execution & Engineering Evidence、N2 Validation & Report Completion、N3 Engineering Memory & Policy Foundations 及 N4 Workflow Recovery & Operational Hardening 已完成。它覆盖 Thread/Turn correlation、持久 Attempt/Step、SDK stream/interrupt/steer/resume、Git evidence、Rules/Context、L1–L5 Validation/Regression/Review/Acceptance、Task Report、accepted-only Memory、minimal Policy，以及 Budget、Cancellation、Recovery、Integrity Scan、Protocol Migration 和 Doctor。V1 单 Agent 工程闭环及本地操作可靠性基础已经形成。

本地 UI Developer Preview 也已完成：标准库 loopback Control API + 原生 HTML/CSS/JS，可从界面完成初始化、创建任务、运行/恢复、验证、审核、验收和证据查看。它不改变 V1 非目标：没有远程部署、用户系统、数据库、复杂前端构建或 Web SaaS。

**N1 Controlled Execution & Engineering Evidence 已完成**：直接复用官方 Python SDK 的 `Thread.turn()`、`TurnHandle.stream()/interrupt()/steer()`，交付持久 ExecutionAttempt/Step、Git baseline/current evidence、Rules、bounded Context Package、Doctor 和薄 UI 投影。N1 未修改 Codex Core，upstream patch 为 0。详细结果见 [N1_VALIDATION_REPORT.md](N1_VALIDATION_REPORT.md)。下一阶段为 **N2 Validation & Report Completion**。

### 第一目标

```text
forge init
  → generate .forge/
  → load forge.yaml
forge task new
  → allocate FORGE-0001
  → persist task atomically
  → validate state machine
forge task show FORGE-0001
  → render persisted task and audit references
```

### 第一批开发任务

| Task | Scope | Files | Acceptance | Risk |
| --- | --- | --- | --- | --- |
| M1-01 Python domain scaffold | 在现有 package 内新增最小 domain/service 模块 | `forgeos/src/forgeos/` | 独立 pytest/compile 通过；不依赖 `codex-core` | Low |
| M1-02 ForgeConfig schema | 定义 forge/project/runtime/task/execution/validation/git/audit；严格解析未知版本 | `forgeos/src/forgeos/config.py`, fixtures | 有效 `forge.yaml` round-trip；缺失/未知版本给出可操作错误 | Low |
| M1-03 `forge init` service | 原子创建需求规定的 `.forge/` 骨架；现有目录不覆盖 | Python store/service；CLI 为薄封装 | 空仓库生成确定性布局；重复执行幂等；冲突文件保持不变 | Medium：文件覆盖安全 |
| M1-04 ForgeTask model | 需求字段、schema/revision | `forgeos/src/forgeos/task.py` | FEATURE/FIX/REFACTOR/REVIEW/DOC/TEST round-trip；字段有上限；ID 稳定 | Low |
| M1-05 TaskStateMachine | 精确实现正常、Repair 和异常状态转换 | `forgeos/src/forgeos/task_state.py` | 合法转换通过；非法转换不写盘；无 evidence 不能 DONE | Medium：需求核心语义 |
| M1-06 `task new/show` service | 单调分配 ID、原子持久化；CLI 只调用 service | Python service/CLI adapter | 首个 ID 为 FORGE-0001；进程重启后读取一致；并发不覆盖 | Medium：并发/原子性 |
| M1-07 Audit skeleton | append-only JSONL event envelope，脱敏规则和 object revision | Python audit module、`.forge/logs/` | init/new/transition 均有事件；损坏尾记录可诊断；不记录秘密 | Medium |
| M1-08 Service/CLI integration tests | service 为主，CLI 只测单次命令边界 | `forgeos/tests/` | `init → new → show` 通过；SDK 多轮路径不依赖 CLI 进程 | Low |
| M1-09 Protocol documentation | 固化 `.forge` layout、schema version 与 migration policy | `docs/forgeos/`, crate-level docs | 文档与 fixture/schema 一致；能从空仓库重现实例 | Low |

### M1 验收边界

- 不启动复杂 Agent workflow 也能独立管理 Project/Task。
- 不修改 Codex Core Agent Loop、Shell、Sandbox、MCP 或 Context Runtime。
- `forge init` 从不覆盖已有用户文件。
- 每次状态变更原子、可审计、可恢复。
- Forge task 的 DONE 不可由普通 CLI 文本或 Agent claim 直接设置。
- Format、build、targeted tests、lint 全部通过；依赖变更同步 Bazel lock。

## 4. M2 — Execution

对应需求基线的 ForgeWorkflow、ForgeExecution、Task→Codex Runtime、ExecutionStep 和 Audit。在 M1 稳定后：

- 关联 ForgeTask ↔ Codex Thread/Turn。
- 通过 Python SDK start/resume/run/stream 控制多轮执行。
- 通过 SDK developer instructions 注入有界 Task/Rules context。
- 通过 SDK Thread/Turn/Item/Token 事件写脱敏 Audit。
- 默认 `ApprovalMode.deny_all`；ForgePolicy 只能显式、可审计地放宽。
- 只有 SDK 公共 API 出现可验证缺口时才提案原始 App Server 或 Extension patch。

验收：不改 Agent Loop 即可完成关联、上下文和审计；Codex 未启用 Forge 时行为不变。

## 5. M3 — Validation

- 定义 Build、Test、Regression、Acceptance、ValidationPlan、CheckResult、Evidence 和 budget。
- 使用 Stop hook 建立 PASS/FAIL→REPAIR 原型。
- 运行 build/test/lint/custom checks，并与 Git baseline 比较。
- PASS 后进入 Review/Acceptance；FAIL 生成 bounded repair continuation。
- 验证取消、超时、预算耗尽、resume 和崩溃恢复。
- 只有 Stop hook 的局限被实证后，才提案 typed `CompletionGateContributor`。

验收：Codex final message 不能绕过 validation；失败可修复；预算耗尽进入 BLOCKED；所有决策有 evidence。

## 6. M4 — Engineering Intelligence

- 实现 Review 与经过接受的 ForgeMemory。
- 只沉淀有来源、版本和失效规则的 Decision、Failure、Pattern。
- 可复用 Codex Review/Memory 机制产生候选，但 Forge ReviewState 和 Memory acceptance 独立。
- DONE 只在 validation、regression、review、acceptance 条件齐备时产生。

N3 已交付 M4 的最小基础：Decision/Failure/Pattern/Task Memory 使用人工接受、文件存储、确定性 bounded selection；ForgePolicy 只在 Forge-owned Task path 与 validation argv 边界执行 additive DENY。详细协议与证据见 [MEMORY_POLICY_PROTOCOL.md](MEMORY_POLICY_PROTOCOL.md) 和 [N3_VALIDATION_REPORT.md](N3_VALIDATION_REPORT.md)。

N4 已完成 execution attempt budget、durable Cancellation、startup Task/Attempt reconciliation、Evidence Integrity Scan 和 additive Protocol Migration。详细协议和证据见 [N4_OPERATIONAL_PROTOCOL.md](N4_OPERATIONAL_PROTOCOL.md) 与 [N4_VALIDATION_REPORT.md](N4_VALIDATION_REPORT.md)。

N5 已完成稳定 protocol fixtures、verified export/atomic import、package `0.2.0` release gates、bounded Audit Query 和 Memory/Policy Operator UX。详细协议与证据见 [N5_RELEASE_PROTOCOL.md](N5_RELEASE_PROTOCOL.md) 与 [N5_VALIDATION_REPORT.md](N5_VALIDATION_REPORT.md)。

ForgeOS V1 本地单 Agent harness 已达到 release-candidate 功能边界。下一阶段为 **R1 — V1 Release Candidate & Distribution**：配置 `origin`、提交/评审、CI matrix、tag、wheel 发布与制品签名。R1 不增加 Agent、Router、数据库或远程 Console 功能；需求中的 M5（Model Router、Agent Roles、Parallel Task、Agent Handoff）保留为 V1 之后。

R1 已完成：公开 ForgeOS `origin`、PR 评审、3 OS × Python 3.10–3.13 CI matrix、wheel/sdist 内容门禁、SHA-256、SPDX SBOM、GitHub build provenance/SBOM attestations、`forgeos-v0.2.0` tag 与 GitHub Release。V1 暂不发布 PyPI；TestPyPI/PyPI 仅保留为未来手动可选目标，不阻塞 GitHub Release。

V1.1 的第一个切片 **Real Project Pilot & Operator UX** 已完成：ForgeOS 自身作为真实工程试点，增加 Doctor 就绪摘要、逐状态推荐下一步、诊断与 Task Report 导出，以及可选的 `forge ui --open-browser`。它仍是本地、单 Agent、文件持久化的薄控制面，没有引入远程服务、数据库、Multi-Agent 或 Model Router。实现计划与验证证据见 [V1_1_DEVELOPMENT_PLAN.md](V1_1_DEVELOPMENT_PLAN.md) 和 [V1_1_VALIDATION_REPORT.md](V1_1_VALIDATION_REPORT.md)。下一切片是在一个刻意受限、非破坏性的真实任务上跑通 CREATED → DONE，并把生成的 Task Report 作为 `0.2.1` 候选发布证据。

## 7. V1 Exit Criteria

- `.forge/` protocol 有 schema、版本与迁移策略。
- Project/Task/Workflow 状态可从文件和 audit 重建。
- Context 注入有边界、稳定、不会重写历史。
- Tool policy 不能降低 Codex Sandbox/Approval。
- Validation/repair loop 有预算、取消、resume 和 evidence。
- Agent、Codex Turn、ForgeTask 的 completion 语义清晰分离。
- 上游更新可通过 Patch Registry 和 regression suite 验证。
- 无大型数据库、向量库、Web UI、复杂 Multi-Agent 或 Router 负担。
