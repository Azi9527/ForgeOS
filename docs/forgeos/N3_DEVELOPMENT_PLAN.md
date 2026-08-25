# ForgeOS N3 Development Plan — Engineering Memory & Policy Foundations

> 状态：**COMPLETE（2026-08-24）**。验收证据见 [N3_VALIDATION_REPORT.md](N3_VALIDATION_REPORT.md)。

## 1. 阶段目标

N3 在 N2 的工程闭环上增加两项基础治理能力：经过人工接受、可追溯的工程记忆，以及位于 ForgeOS 自有边界上的最小 fail-closed Policy Gate。N3 不把历史全文塞入 Prompt，也不声称替代 Codex Sandbox、Approval 或工具运行时。

```text
Decision / Failure / Pattern / Task candidate
  → DRAFT
  → human ACCEPT / REJECT
  → deterministic Retrieve / Rank / Select
  → bounded Context Fragment + Selection Evidence

Task / Validation Plan
  → ForgePolicy Evaluation
  ├─ PASS → baseline / Codex / validation
  └─ DENY → no external execution
```

## 2. 进入基线

| Item | N3 entry baseline |
| --- | --- |
| Upstream | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| N2 tests | 73 passed |
| Memory | 只有空目录，无领域模型、接受或检索协议 |
| Policy | Codex 自有 Sandbox/Approval；ForgeOS 无独立静态 Gate |
| Upstream patch | None |

## 3. Work packages

| ID | Deliverable | Acceptance | Status |
| --- | --- | --- | --- |
| N3-00 | 需求、源码与基线冻结 | N2 73-test baseline 与 Git 状态记录 | Complete |
| N3-01 | Memory lifecycle | 四类 Memory、DRAFT/ACCEPTED/REJECTED/SUPERSEDED、revision/hash、人工权限 | Complete |
| N3-02 | Retrieval + Context | accepted-only、稳定加权排序、8 条/16 KiB 上限、脱敏、selection evidence | Complete |
| N3-03 | Memory production | Validation 失败产生 Failure draft；DONE 产生 Task draft；报告反向关联 | Complete |
| N3-04 | Minimal Policy | `.git`/workspace boundary、非破坏性 validator、项目 DENY 文件、pre-execution fail-closed | Complete |
| N3-05 | Product surfaces | CLI、Control API、loopback HTTP API、任务证据 UI、Audit、Doctor | Complete |
| N3-06 | Recovery/security/tests | 原子写、revision conflict、重启 round-trip、权限/密钥/边界测试 | Complete |
| N3-07 | Protocol/report/roadmap | 协议、计划、验收报告、Roadmap 与 Patch Registry 更新 | Complete |

## 4. Scope boundaries

N3 Policy 只控制 ForgeOS 当前真实拥有的边界：Task `related_modules` 路径以及 ForgeOS 将执行的 validation argv。Codex Turn 内的 Shell/File/MCP tool calls 仍由 Codex Sandbox、Approval 和官方 Runtime 控制；在没有可验证 SDK/App Server hook 前，不宣称 ForgePolicy 已覆盖这些调用。

明确不进入：向量数据库、embedding、RAG 平台、无限历史、自动接受模型记忆、复杂规则语言、Multi-Agent、Model Router、远程 Web Console、数据库或分布式队列。

## 5. Exit criteria

- Agent/model 身份不能接受、拒绝或 supersede Memory。
- 只有 ACCEPTED 且未 supersede 的记录可进入 Context。
- 检索和选择对相同输入可重复，并持久化 hash、score、reason、bytes 与 truncation。
- Policy 在 baseline、Codex 执行和 validation 之前生效；无用户 ALLOW 可削弱 built-in DENY。
- Failure/Task 自动产物保持 DRAFT，必须人工判断后才能复用。
- 所有新状态可从 `.forge/` 和 Audit 重建；旧项目通过 additive layout 迁移。
- 无 Codex-owned 文件修改。

## 6. Next stage

建议下一阶段为 **N4 — Workflow Recovery & Operational Hardening**：预算/取消/崩溃恢复演练、显式 repair budget、evidence integrity scan、协议 migration 命令和更完整的本地运维视图。仍不进入 Multi-Agent、Model Router 或远程 SaaS。
