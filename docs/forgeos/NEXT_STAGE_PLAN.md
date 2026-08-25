# ForgeOS Next Stage Plan — N1 Controlled Execution & Engineering Evidence

> 状态：**COMPLETE（2026-08-24）**。C18–C25 全部完成；最终证据见 [N1_VALIDATION_REPORT.md](N1_VALIDATION_REPORT.md)。下一阶段为 N2 Validation & Report Completion。

## 1. 阶段定位

N1 是当前 Python SDK-first 纵向切片之后的下一开发阶段。它不是重新开始 M1，也不进入复杂 M4/M5；它关闭 M2 的运行控制缺口，并建立 M3 Regression、Acceptance 和 Task Report 所必需的工程证据。

```text
Current slice
  Task → Codex run → Validation → Review → Acceptance
        ↓
N1
  controlled Turn + progress/interrupt/resume
  + Git baseline/final evidence
  + Rules/Context Package
  + persistent ExecutionAttempt/Step
  + Doctor and thin UI projection
        ↓
Next gate
  typed L1-L5 Validation + Regression + criteria Acceptance + Task Report
```

本阶段继续遵守：Maximum Reuse、Minimum Intrusion、Agent != Authority、Validation First。预计 upstream patch 数量为 **0**。

## 2. 当前真实基线

基线日期：2026-08-24。

| 项目 | 当前证据 |
| --- | --- |
| Upstream | `openai/codex`，branch `main`，commit `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| Forge runtime | 独立 `forgeos/` Python package；官方 `openai-codex` SDK |
| SDK capability | `Thread.run()` 已使用；当前 SDK 还提供 `Thread.turn()`、`TurnHandle.stream()`、`interrupt()`、`steer()` |
| Domain | ForgeProject、ForgeConfig、ForgeTask、TaskStateMachine、Review/Acceptance evidence |
| Persistence | `.forge/`、原子写、revision check、Task ID、Audit、Execution/Validation records |
| Workflow | Run/Resume → independent Validation → Repair → Review → Acceptance |
| Control surface | token-protected loopback HTTP API、本地 Web UI、background jobs |
| Verification | `69 passed`；Ruff/Node/wheel/browser 全部通过；官方 `openai-codex 0.147.0` controlled stream smoke 成功 |
| Upstream changes | None |

### 2.1 阶段开始时确认的缺口（现已关闭）

- 同步 `Thread.run()` 期间只有 Job RUNNING，缺少结构化进度、interrupt 和 steer。
- background Job 是进程内投影；进程重启后无法解释未完成 attempt。
- ExecutionRecord 以 Turn 为单位，未形成需求规定的 ExecutionStepResult。
- Task 开始前未记录 Git HEAD/branch/status，结束后未记录 final diff。
- `.forge/rules/` 和 Context Package 尚未进入真实执行链。
- Validation 只有 command checks；尚不能区分 baseline failure 与新增 regression。
- `forge doctor` 尚未实现。
- UI 的审核/验收身份当前使用本地占位身份；需要页面内显式、可审计的身份和确认交互。

## 3. N1 目标与非目标

### 3.1 目标

1. 长时间 Codex Turn 有可观察进度，可由用户安全 interrupt，并能基于持久 Thread 恢复。
2. 每次执行在模型运行前提交 Git baseline evidence，在运行后提交 current/final evidence。
3. 建立 versioned、bounded、source-visible 的 ForgeRules 与 Context Package。
4. 建立可恢复的 ExecutionAttempt/ExecutionStep 持久协议，进程内 Job 只作为缓存。
5. 增加只读 `forge doctor` 和薄 UI 投影，让用户能看到进度、基线、差异和上下文来源。
6. 为下一阶段 Regression、criteria-by-criteria Acceptance 和 Task Report 提供稳定输入。

### 3.2 非目标

- 不修改 Codex Agent Loop、Shell、Sandbox、Approval、MCP 或 App Server protocol。
- 不引入 Rust crate、数据库、消息队列、前端框架或远程部署。
- 不实现 Memory/RAG、Multi-Agent、Model Router、自动 PR/commit/push。
- 不允许 ForgePolicy 放宽 Codex 安全策略。
- 不在 N1 宣称完整 L1-L5 Validation、完整 Task Report 或 V1 DONE。
- 不把原始 SDK notification、完整 diff、完整环境变量或 secret 无界写入 Audit/Context。

## 4. 目标架构

```text
Local UI / Python caller
  ↓
ForgeControlService
  ├─ persistent ExecutionAttempt
  ├─ progress / interrupt / resume
  └─ read-only projections
  ↓
ForgeWorkflowService
  ├─ GitEvidenceService.capture_baseline()
  ├─ RuleResolver.resolve()
  ├─ ContextPackageBuilder.build()
  ├─ ForgeExecutionService
  │    └─ CodexSdkGateway.start_turn()
  │         └─ TurnHandle.stream / interrupt / steer
  ├─ GitEvidenceService.capture_current()
  └─ ValidationRunner
  ↓
.forge/
  ├─ execution-attempts/<task>/<attempt>.json
  ├─ evidence/git/<task>/<snapshot>.json
  ├─ context/packages/<task>/<package>.json
  ├─ rules/*.md
  └─ logs/audit.jsonl
```

依赖方向保持 `web/cli → control/workflow → domain adapters → official SDK/Git process`。SDK/Git 结果只能形成 evidence，不能直接写 Task status。

## 5. 工作包

| ID | Depends | Scope / Deliverables | Primary files | Acceptance | Risk / Size |
| --- | --- | --- | --- | --- | --- |
| N1-01 | Current baseline | 冻结 N1 schema/API、安全预算和 migration 规则；为当前 schema v1 定义 additive reader | `config.py`, `models.py`, protocol docs/fixtures | 旧 `.forge` 可读；未知新版本 fail closed；无静默字段丢失 | High / S |
| N1-02 | N1-01 | `ExecutionAttempt`、`ExecutionStepResult`、状态与 evidence reference；原子持久化 | new `execution_records.py`, `storage.py`, tests | queued/running/completed/failed/interrupted 可表达；重启后 running 被诊断为 interrupted，不伪装成功 | High / M |
| N1-03 | N1-02 | SDK controlled turn adapter：`Thread.turn()` + `TurnHandle.stream()`；bounded/redacted progress | `codex_sdk.py`, new `execution_events.py`, tests | fake SDK contract 覆盖 stream/result/error；event 有 task/thread/turn correlation；内存和持久输出有硬上限 | High / L |
| N1-04 | N1-03 | interrupt、steer 和 resume；每 Task 单 active handle；明确竞态语义 | `codex_sdk.py`, `control.py`, `execution.py`, tests | interrupt 幂等；terminal race 不产生双完成；resume 使用原 Thread；无 active turn 时返回 typed conflict | High / L |
| N1-05 | N1-01 | 只读 `GitEvidenceService`：repo/HEAD/branch/status/diff hash/changed files/baseline | new `git_evidence.py`, config/model/store, tests | 所有 Git 命令 argv + `shell=False` + timeout；不执行 add/commit/reset；non-repo、detached HEAD、dirty tree 有确定结果 | High / M |
| N1-06 | N1-05 | baseline/current evidence 进入 Workflow；Validation 可引用 baseline | `workflow.py`, `execution.py`, audit, tests | Codex 前 baseline committed；Turn 后 current snapshot committed；失败/interrupt 仍保留 evidence；Task 不能伪造 commit/diff | High / M |
| N1-07 | N1-01 | `RuleRecord` 与 deterministic `RuleResolver`；Global→Project→Module→Task，来源/hash/severity/enforcement | new `rules.py`, `.forge` templates, tests | 稳定顺序；重复 ID/同 scope 冲突报错；较低层不能静默降级 BLOCK；无规则时产生显式空结果 | High / M |
| N1-08 | N1-05, N1-07 | bounded `ContextPackage`：Project、Task、Rules、Git baseline；SDK developer instructions adapter | new `context.py`, `codex_sdk.py`, `workflow.py`, tests | 每 fragment 记录 source/hash/bytes/truncation；单项 ≤8 KiB、总包默认 ≤32 KiB；外部内容不提升为 developer authority；相同输入输出确定 | High / L |
| N1-09 | N1-02, N1-04, N1-06, N1-08 | `forge doctor`、Control API 投影与本地 UI：progress、interrupt、Git/context evidence、页面内 reviewer/acceptor dialog | `cli.py`, `control.py`, `web_server.py`, `web/*`, tests | Doctor 只读且输出 PASS/WARN/FAIL；运行中按钮有 progress/cancel；确认框不使用 `window.prompt`；身份进入 Audit | Medium / L |
| N1-10 | All N1 | recovery/security/regression suite、真实 SDK opt-in smoke、文档和 validation report | `forgeos/tests/`, `docs/forgeos/` | Quality Gates 全 PASS；重启/interrupt/resume/dirty repo/context budget/secret redaction 覆盖；upstream patch 仍为 0 | High / L |

## 6. Change 序列

每个 change 必须可独立测试，复杂逻辑变更控制在 500 行以内，机械变更总量控制在 800 行以内。

| Change | Work packages | 可独立验收结果 |
| --- | --- | --- |
| C18 | N1-01, N1-02 | versioned ExecutionAttempt/Step 可落盘并从中断进程恢复 |
| C19 | N1-03 | SDK TurnHandle stream 适配，但尚不开放 UI interrupt |
| C20 | N1-04 | interrupt/steer/resume service contract 与竞态测试通过 |
| C21 | N1-05, N1-06 | Task run 自动产生 baseline/current Git evidence |
| C22 | N1-07 | Rules 文件协议与 deterministic resolver |
| C23 | N1-08 | bounded Context Package 注入真实 SDK turn |
| C24 | N1-09 | Doctor、Control API 和 UI 消费上述能力 |
| C25 | N1-10 | recovery/security/real SDK/browser 验证和文档关闭阶段 |

禁止把 C18–C25 合并为一个大 change。C19 只有 fake SDK 合同通过后才能进入 C20；C21 未通过前不得实现 Regression 判定。

完成结果：C18–C25 均已通过各自测试与最终联合回归。实现保持为 ForgeOS-owned Python/HTML/CSS/JS 文件，没有创建任何 Active upstream patch。

## 7. 持久协议与迁移

N1 采用 additive schema，不直接重写现有 Task 文件。

- `ForgeTask.schema_version` 保持 1；新增大对象通过 evidence reference 外置。
- ExecutionAttempt/Step、GitSnapshot、RuleResolution、ContextPackage 各自携带 `schema_version`。
- 旧执行记录继续可读；新的 attempt reader 不把旧记录伪装成 step-complete。
- 进程启动时扫描 `RUNNING` attempt，只允许原子标记为 `INTERRUPTED`；不得自动重跑模型或命令。
- large diff/context/event body 外置并记录 SHA-256、byte size、truncated/redacted 标记。
- 任何 migration 先保留备份或使用同目录临时文件 + atomic replace；损坏源文件保留并 fail closed。

## 8. SDK 控制语义

### 8.1 Progress

- SDK notification 经 allowlist 映射为 Forge progress event；未知类型只记录 type/count，不保存任意 payload。
- UI 显示 phase、elapsed time、最近安全摘要，不显示 secret、完整 tool arguments 或无界模型内容。
- progress 丢失不得影响 authoritative Task/Attempt 状态。

### 8.2 Interrupt

```text
RUNNING
  ├─ terminal result first → commit terminal result; later interrupt is no-op/conflict
  └─ interrupt accepted first → commit INTERRUPTING → INTERRUPTED
```

- interrupt 只停止当前 Turn，不删除 Thread、不清理用户文件、不回滚 Git。
- interrupt 后 Task 进入可恢复的 `BLOCKED`/明确 interrupted evidence；用户触发 resume 才开始下一 Turn。
- server restart 不假定子进程仍可控制；未完成 attempt 标记 interrupted 并给出恢复说明。

### 8.3 Steer

- steer 只在 active handle 上可用，文本有大小上限并写 hash/audit summary。
- steer 不修改 Task objective、acceptance 或 rules；这些权威输入必须走独立 Task update/migration。

## 9. Git Evidence 与安全

只允许只读命令：

```text
git rev-parse --show-toplevel
git rev-parse HEAD
git branch --show-current
git status --porcelain=v1 -z
git diff --name-status -z
git diff --numstat -z
```

具体 argv 在实现时按当前 Git 能力验证；计划中的概念命令不是未经测试的最终命令。禁止 `git add/commit/reset/checkout/clean`。Diff evidence 默认保存统计、changed paths 和 hash；完整 diff 受大小、secret 和二进制策略约束。

Baseline policy：

- clean repo：记录 HEAD + clean status。
- dirty repo：记录 HEAD + dirty path set/hash，不擅自 stash/commit；Task evidence 明确 existing vs task-time changes 的判定限制。
- non-repo：允许非 Git 项目运行，但 Regression/Task Report 对 Git 相关 gate 返回明确 WARN/SKIP，required policy 可 fail closed。
- submodule/worktree/detached HEAD：保留真实状态，不猜 default branch。

## 10. Rules 与 Context 预算

- Rules 来源优先使用结构化 front matter + Markdown body；文件必须位于 canonical `.forge/rules/`。
- 解析顺序和冲突决议确定性，Rule ID/version/hash 进入 Context Package。
- Context Package 只包含当前 Task 必需的 Project、Task、selected Rules 和 Git baseline 摘要。
- 单 fragment 最大 8 KiB，总 package 默认最大 32 KiB；同时记录 UTF-8 bytes 和可用的 runtime usage。该 byte cap 是无 tokenizer 依赖时的保守硬边界。
- 任何单 fragment 预计超过 1K tokens 必须在实现评审中标记；不得超过上游 10K-token 单项限制。
- 不注入完整 Audit、完整 Git diff、整个仓库或未接受 Memory。

## 11. 测试计划

### 11.1 自动化矩阵

| Area | Required cases |
| --- | --- |
| Attempt/Step | round-trip、revision conflict、terminal race、crash residue、corrupt record |
| SDK handle | stream、result、error、interrupt before/after terminal、steer、same-thread resume |
| Git | clean/dirty/untracked/detached/non-repo/timeout/non-zero/binary/路径含空格和 Unicode |
| Rules | layer order、duplicate ID、BLOCK downgrade、invalid front matter、symlink/path escape |
| Context | deterministic hash、source refs、per-item/total truncation、untrusted separation、secret fixture |
| Doctor | missing SDK/Git/config/layout、healthy workspace、read-only behavior、stable exit codes |
| HTTP/UI | token、cancel route、progress projection、decision dialog、duplicate action、server restart |
| Workflow E2E | run→progress→interrupt→resume→validation；run→baseline→context→PASS |

### 11.2 Quality commands

```powershell
Push-Location forgeos
python -m pytest
ruff check --no-cache .
ruff format --no-cache --check .
node --check src\forgeos\web\app.js
Pop-Location
```

真实 SDK smoke 必须显式 opt-in，先使用 read-only/deny-all fixture；workspace-write 场景只在隔离 fixture repository 执行。没有 upstream Rust patch 时不运行全量 Rust workspace baseline；出现 patch 提案时先进入 G0。

## 12. N1 可见验收场景

1. 在隔离 Git fixture repository 执行 `forge doctor`，所有必需项 PASS。
2. 创建 FEATURE Task；Run 前页面显示 baseline commit、branch、dirty status。
3. 启动 Codex 后页面立即显示 phase/elapsed，并禁止重复 Run。
4. 用户 interrupt；Attempt 持久为 INTERRUPTED，Task 不进入 DONE，server restart 后证据仍可见。
5. 用户 resume；复用同一个 Codex Thread，形成新的 Attempt/Turn。
6. Context evidence 显示 selected rule IDs、source/hash/size/truncation，不显示 secret。
7. Turn 完成后显示 changed files、current commit/diff hash，并进入独立 Validation。
8. Review/Acceptance 使用页面内身份与确认，不依赖原生 `prompt()`。
9. 删除所有进程内 Job 状态并重启 UI，仍能从 `.forge` 重建 Attempt、Git、Context 和 Task 投影。

## 13. N1 Exit Gate

- 长时间 Turn 可观察、可 interrupt、可同线程 resume。
- 执行状态以持久 Attempt/Step 为权威，Job 内存投影不再是唯一解释来源。
- 每个 Run 都有不可伪造的 Git baseline/current evidence，且 ForgeOS 不修改 Git。
- Rules/Context 注入 bounded、deterministic、source-visible、fail closed。
- Doctor、Control API 和 UI 只消费 service 能力，不直接写 Task status。
- format/lint/tests/browser/real SDK opt-in evidence 完整；失败根因和未执行项明确。
- Codex-owned/upstream 文件修改仍为 None；若不再为 None，N1 停止并先进入 G0 baseline gate。

## 14. N1 后续阶段

N1 完成后的 **N2 Validation & Report Completion 已于 2026-08-24 完成**。计划和证据见 [N2_DEVELOPMENT_PLAN.md](N2_DEVELOPMENT_PLAN.md) 与 [N2_VALIDATION_REPORT.md](N2_VALIDATION_REPORT.md)：

- typed L1 Build / L2 Unit / L3 Integration / L4 Regression / L5 Acceptance；
- baseline failure 与新增 regression 区分；
- acceptance criteria-by-criteria evidence；
- Review checklist（architecture/quality/risk/tests/compat/debt）；
- Forge Task Report（changed files、commands、start/end commit、final diff、repair、risk/debt）；
- 一个隔离 fixture feature 完整经历失败→修复→验证→审核→验收→DONE。

Memory、Multi-Agent、Model Router 和远程 Web Console 继续不进入 N2。

下一推荐阶段为 **N3 Engineering Memory & Policy Foundations**；仍不进入 Multi-Agent、Model Router、向量数据库或远程 Web Console。
