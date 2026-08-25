# ForgeOS N5 Development Plan — Release Readiness & Operator UX

> 状态：**COMPLETE（2026-08-25）**。验收证据见 [N5_VALIDATION_REPORT.md](N5_VALIDATION_REPORT.md)。

## 1. 阶段目标

N5 将 N1–N4 的本地单 Agent 工程闭环整理为可验证、可迁移、可操作的 V1 release candidate。它不增加 Agent 能力，也不修改 Codex Runtime；重点是稳定 ForgeOS-owned 协议与运维入口。

```text
Protocol v1 fixtures → canonical round-trip
Evidence Integrity → deterministic export → hash verify → atomic import
Release manifest → six readiness gates → persisted report
Audit JSONL → bounded filters → cursor page
Memory / Policy → human-governed local Operator UX
```

## 2. 进入基线

| Item | N5 entry baseline |
| --- | --- |
| Upstream | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| N4 tests | 92 passed |
| Doctor | 11/11 PASS |
| Protocol | v1 current；无兼容 fixtures |
| Portability | 无 export/import contract |
| Operator UX | 任务与 N4 Operations；Memory/Policy 无管理界面 |
| Upstream patch | None |

## 3. Work packages

| ID | Deliverable | Acceptance | Status |
| --- | --- | --- | --- |
| N5-00 | Entry baseline | N4 tests、Doctor、Git commit/status 冻结 | Complete |
| N5-01 | Protocol fixtures | Config/Task/Policy/Protocol 四个 v1 fixture canonical round-trip | Complete |
| N5-02 | Bundle protocol | bounded export、SHA-256 manifest、safe verify、empty-target atomic import | Complete |
| N5-03 | Release readiness | package `0.2.0`、release manifest、六项 gate、持久报告 | Complete |
| N5-04 | Audit query | task/type/actor filter、sequence cursor、200 hard limit | Complete |
| N5-05 | Operator UX | Release、Memory create/decide、Policy create/retire、Audit filter | Complete |
| N5-06 | Adversarial tests | tamper、duplicate ZIP、collision、authority、migration、HTTP/UI | Complete |
| N5-07 | Exit evidence | 101 tests、Doctor、wheel、real bundle、browser、docs | Complete |

## 4. Scope boundaries

- Bundle 只包含 `.forge` 权威状态，不打包工作区源码、Git objects、凭证或 Codex 登录状态。
- Import 仅允许目标 `.forge` 不存在；先完整验证，再写 staging，最后原子替换。
- 导入时只重绑定 `project.root`，不改变 Project ID、Task、Audit 或其他工程证据。
- Policy UI 只能创建 additive `DENY`；内建规则不可退役，项目规则退役后移入证据目录，不删除。
- Audit query 永不重写 JSONL；结果按 sequence 升序，单页最多 200 条。
- Release gate 不替代测试执行；它验证已安装包的静态协议、状态完整性与操作资产。

明确不进入：远程 Console、账户/IAM、数据库、云存储、自动发布、Multi-Agent、Model Router、向量检索、Codex Core Hook。

## 5. Exit

N5 完成后，ForgeOS V1 本地单 Agent harness 已具备 release-candidate 所需的协议、可移植性、发布自检和操作界面。真正的发布仍需仓库 `origin`、提交、CI、tag 和制品签名；这些属于 **R1 — V1 Release Candidate & Distribution**，不应通过本地工作树隐式完成。
