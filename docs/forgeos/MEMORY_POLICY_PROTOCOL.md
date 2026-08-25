# ForgeOS Memory & Policy Protocol v1

## 1. File layout

```text
.forge/
├─ memory/
│  ├─ decisions/<memory-id>.json
│  ├─ failures/<memory-id>.json
│  ├─ patterns/<memory-id>.json
│  ├─ tasks/<memory-id>.json
│  └─ selections/<task-id>/<selection-id>.json
├─ policies/<policy-id>.json
└─ policy/evaluations/<task-id>/<evaluation-id>.json
```

所有 JSON record 使用 `schema_version: 1`、同目录临时文件、`fsync` 和 atomic replace。Memory 决策使用 object revision lock；内容 hash 覆盖 kind/title/body/tags/modules，加载时重新验证。

## 2. MemoryRecord

类型为 `DECISION | FAILURE | PATTERN | TASK`。状态为：

```text
DRAFT ──human accept──> ACCEPTED ──human supersede──> SUPERSEDED
  └────human reject──> REJECTED
```

模型、Agent、Codex 或 assistant 身份不能执行状态决策。自动产生的 Validation Failure 与 completed Task knowledge 永远先落为 DRAFT。记录保留 created/decided authority、时间、原因、来源 Task/Report、revision、hash 和 replacement link。

边界：title 200 UTF-8 bytes；body 8 KiB；tags 最多 50；related modules 最多 100。Audit 单事件仍受 64 KiB 上限和 key-based secret redaction。

## 3. Retrieval contract

检索只扫描 `ACCEPTED`。query 由 Task title、objective、related modules 形成；对 title/tags/modules/body 采用固定权重 `8/6/5/1`，exact module 另加 20。排序键为 `(-score, memory_id)`，因此相同文件状态和 Task 输入产生同一选择。

选择最多 8 条、总渲染内容最多 16 KiB。超出时记录 `truncated=true`，不会产生无界 Prompt。每个 selection 保存 query hash、memory ID、content hash、score、match reasons、bytes 和总量。Context Package 以 `RUNTIME_DATA` 注入，并明确其是证据而非提高权限的 developer rule；常见 token/password/secret/API key 形式在注入前脱敏。

## 4. ForgePolicy file

项目 Policy 是 additive DENY：

```json
{
  "schema_version": 1,
  "id": "project.no-production",
  "name": "No production changes",
  "effect": "DENY",
  "target": "TASK_PATH",
  "patterns": ["production/**"],
  "reason": "production access requires a separate approved workflow"
}
```

`target` 当前支持 `TASK_PATH` 与 `VALIDATION_COMMAND`。N3 不支持用户 `ALLOW`，因此项目文件不能覆盖 built-in protection。未知 schema、重复 ID、空 pattern 或 ALLOW 文件均 fail closed。

Built-ins：

- Task path 不得逃逸 workspace，也不得指向 `.git` metadata。
- Forge validation argv 不得以 `rm/rmdir/del/format/shutdown/reboot` 或 mutating Git `reset/clean/checkout/restore/commit/push` 开始。
- Validation 继续使用 argv array、`shell=False`、timeout 和 bounded output。

每次 evaluation 保存 input/rules hash、参与 rule IDs、PASS/DENY 和结构化 violations，并写 `policy.evaluated` 或 `policy.denied` Audit。

## 5. Enforcement boundary

ForgePolicy 在 Forge workflow baseline、Codex execution 和 validation retry 前运行。它不能拦截官方 Codex Runtime 内部未知的每一个 tool call；该层仍由 Codex Sandbox/Approval/MCP policy 负责。未来只有在公共 SDK/App Server 提供稳定 pre-tool hook，且实证现有边界不足时，才提案更深 integration；任何 upstream patch 都必须先进入 Patch Registry。

## 6. Recovery and migration

旧 `.forge/` 项目启动时只补建新目录，不改写旧 Task/Validation/Report。Doctor 检查布局并完整解析所有 Memory 和 Policy 文件。损坏 hash、未来 schema、非法 policy 或 revision conflict 都停止该操作；不会删除记录、自动接受候选或触发模型重跑。
