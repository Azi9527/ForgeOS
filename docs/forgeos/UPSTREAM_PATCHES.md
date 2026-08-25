# Upstream Patch Registry

本登记表覆盖所有对 OpenAI Codex 上游拥有文件的 ForgeOS 修改。ForgeOS 新文件也可在需要解释 integration 时引用，但不计入 upstream patch 数量。

## 字段格式

| 字段 | 含义 |
| --- | --- |
| Patch ID | `FUP-XXXX`，单调编号。 |
| File | 上游相对路径；多个文件应拆成职责清晰的 patch 或列全。 |
| Reason | 现有 Hook/Extension/App Server 为何不足。 |
| ForgeOS Feature | 对应 Forge 能力、EP 和里程碑。 |
| Type | Manifest、Composition、API、Runtime、Protocol、Build。 |
| Conflict Risk | Low/Medium/High，并说明热点原因。 |
| Status | Proposed/Active/Superseded/Dropped/Upstreamed。 |
| Introduced | ForgeOS commit。 |
| Upstream Base | 引入和最后复验的 upstream commit。 |
| Tests | 防止语义漂移的验证。 |

## M0 Registry

**None in M0.** M0 没有修改任何 Codex Core、App Server、CLI、workspace manifest、Sandbox、Approval、MCP 或其他上游源码文件；只新增 `docs/forgeos/`。

## N1 Registry

**None in N1.** Controlled Execution & Engineering Evidence 全部通过 ForgeOS-owned Python SDK adapter、service、协议和本地 UI 实现；没有修改任何 Codex-owned 文件，也没有激活候选 patch。

## N2 Registry

**None in N2.** Typed Validation、Regression、Review、Acceptance 和 Task Report 全部位于 ForgeOS-owned Python/HTML/CSS/JS 模块；未修改 Codex Agent Loop、App Server、CLI、SDK、Sandbox、Approval、MCP 或 workspace manifest。

## N3 Registry

**None in N3.** Engineering Memory、bounded retrieval、Context selection evidence 和 minimal ForgePolicy 全部位于 ForgeOS-owned control layer；未修改 Codex tool runtime、Sandbox、Approval、SDK 或 App Server。

## N4 Registry

**None in N4.** Budget、Cancellation、Recovery、Integrity Scan 和 Protocol Migration 均为 ForgeOS-owned Python/HTML/CSS/JS；未修改 Codex Agent Loop、SDK、App Server、Sandbox、Approval 或工具执行链。

## N5 Registry

**None in N5.** Protocol fixtures、Bundle export/import、Release Readiness、Audit Query 和 Operator UX 全部位于 ForgeOS-owned Python/HTML/CSS/JS 与包资源；未修改任何 Codex-owned 文件。

## R1 Registry

R1 新增的 `.github/workflows/forgeos-*.yml` 是 ForgeOS-owned integration 文件，不覆盖上游 workflow。R1 仅有一个低风险上游仓库文件修改：

| Patch ID | File | Reason | ForgeOS Feature | Type | Conflict Risk | Status | Introduced | Upstream Base | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| FUP-0004 | `.gitignore` | `.forge/` 包含本地运行证据、绝对路径和审计记录，必须阻止进入提交与源码制品；同时忽略 ForgeOS Python build/cache。 | R1 distribution integrity | Build/Repository | Low：只在文件末尾增加 ForgeOS 专属路径 | Active | R1 V1 release-candidate commit | `068c49f075cf287a1fe7d1ee36cf005efac922e7` | `git status --short` 不显示 `.forge/`；distribution gate 不包含 `.forge/` |

## 预计候选（尚不是 Active Patch）

| Patch ID | File | Reason | ForgeOS Feature | Type | Conflict Risk | Status |
| --- | --- | --- | --- | --- | --- | --- |
| FUP-0001 | `codex-rs/Cargo.toml`、必要的 Bazel/lock 文件 | 原计划将 Forge crates 加入 Rust workspace；SDK-first 架构不再需要。 | Former M1 foundation | Manifest/Build | Medium | Dropped |
| FUP-0002 | `codex-rs/app-server/src/extensions.rs` | 原计划安装 Forge extension；只有 Python SDK gap 被验证后才能重新提案。 | EP-02/03/04/05/06 | Composition | Medium | Dropped |
| FUP-0003 | `codex-rs/ext/extension-api/*`, `codex-rs/core/src/session/turn.rs` | 原计划增加 completion gate；当前先在 Forge 控制层独立 Validation。 | EP-07 | API/Runtime | High | Dropped |

Proposed 行不授权实现。编码前必须补全精确文件、替代方案证据、API 形状和测试计划，并把状态改为 Active。

## Patch Record 模板

```text
Patch ID:
Title:
Status:
Owner:
File(s):
Reason:
Rejected alternatives:
ForgeOS feature / extension point:
Type:
Conflict risk:
Introduced ForgeOS commit:
Upstream base commit:
Last verified upstream commit:
Behavioral tests:
Removal condition:
Conflict notes:
```
