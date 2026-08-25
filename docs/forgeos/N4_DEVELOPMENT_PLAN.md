# ForgeOS N4 Development Plan — Workflow Recovery & Operational Hardening

> 状态：**COMPLETE（2026-08-25）**。验收证据见 [N4_VALIDATION_REPORT.md](N4_VALIDATION_REPORT.md)。

## 1. 阶段目标

N4 把 N1–N3 已有闭环从“正常路径可用”推进到“中断、预算耗尽、进程丢失、证据损坏和协议升级时可诊断、可恢复”。它不修改 Codex Runtime，而是在 ForgeOS 自有状态与调用边界增加操作性门禁。

```text
Task + Config + Attempt history
  → Budget Gate
  → Policy Gate
  → Baseline / Codex / Validation

Human cancellation
  → durable REQUESTED
  → interrupt active Turn when available
  → safe-boundary APPLIED
  → CANCELLED

Process restart
  → recover non-terminal Attempt as INTERRUPTED
  → reconcile Task to BLOCKED or CANCELLED
  → persist Recovery Report
```

## 2. 进入基线

| Item | N4 entry baseline |
| --- | --- |
| Upstream | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| N3 tests | 81 passed |
| Recovery | 只把遗留 Attempt 标为 INTERRUPTED；不协调 Task |
| Budget | repair limit 存在，但无执行 Attempt budget/evidence |
| Integrity | 无统一 hash/link/schema 扫描 |
| Migration | layout additive，但无显式 plan/apply/manifest |
| Upstream patch | None |

## 3. Work packages

| ID | Deliverable | Acceptance | Status |
| --- | --- | --- | --- |
| N4-00 | Requirements/source/baseline | 81-test N3 baseline 与 Git 状态冻结 | Complete |
| N4-01 | Explicit Budget | execution attempt limit、repair consumption、persisted evaluation、exhaustion→BLOCKED | Complete |
| N4-02 | Cancellation/Recovery | 人工 durable request、interrupt、safe apply、startup Task reconciliation | Complete |
| N4-03 | Integrity Scan | JSON/schema/symlink/size、Audit、Memory hash、Task evidence links | Complete |
| N4-04 | Protocol Migration | version manifest、plan/apply/status、additive-only、future version fail-closed | Complete |
| N4-05 | Product surfaces | CLI、Control/HTTP API、Doctor、本地运维 UI | Complete |
| N4-06 | Adversarial tests | budget、cancel、crash、tamper、broken link、migration、restart | Complete |
| N4-07 | Quality/report | Ruff、92 tests、wheel、Doctor、browser、real SDK、docs | Complete |

## 4. Scope boundaries

- Attempt budget 由 ForgeOS 计数，不能通过 Agent final response 重置。
- Cancellation 不能强制杀死任意 validation 子进程；它先持久化意图，在已有 Codex control 时请求 interrupt，并在 workflow 安全边界落地。
- Recovery 不自动重放模型或命令。遗留 Attempt 进入 INTERRUPTED，Task 进入 BLOCKED，必须由人决定是否恢复。
- Integrity Scan 是工程证据检查，不是通用 antivirus 或 Git object verifier。
- Migration 只新增目录/manifest/record，不重写 Task、Validation、Memory、Audit 或 Git 历史。

明确不进入：进程级强杀、分布式 lease、远程 worker、数据库、Multi-Agent、Model Router、SaaS/IAM、向量检索或 Codex Core hook。

## 5. Exit criteria

- Attempt budget 在 baseline 和 Codex 之前 fail closed；耗尽产生 evidence 和 BLOCKED。
- Agent/system 身份不能取消 Task；请求幂等、带 revision、受文件锁保护。
- 启动恢复同时修复 Attempt 与 Task 投影，不留下 IMPLEMENTING ghost state。
- Memory hash、Audit sequence、Task→Validation/Regression/Report 断链可被检测。
- 旧项目可预览并执行 additive migration；未来版本拒绝降级读取。
- CLI/API/UI/Doctor 使用同一服务，不存在直接伪造状态的旁路。
- 无 Codex-owned 文件修改。

## 6. Next stage

建议下一阶段为 **N5 — Release Readiness & Operator UX**：稳定 protocol fixtures、export/import、版本发布检查、CI matrix、操作审计查询和 Memory/Policy 管理 UI。仍不进入远程控制台、Multi-Agent 或 Model Router。
