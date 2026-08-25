# ForgeOS N5 Release and Bundle Protocol

## 1. Version contract

| Contract | Value |
| --- | --- |
| Python package | `forgeos-harness 0.2.0` |
| Forge protocol | `1` |
| Bundle schema | `1` |
| Codex Python SDK | `>=0.146,<0.148` |

`release_manifest.json` 是运行时与 wheel 共用的版本事实。Protocol v1 fixtures 位于包内 `protocol_fixtures/v1/`，Config、created Task、additive DENY Policy 和 Protocol manifest 必须通过当前 parser 的无损 round-trip。

## 2. Bundle format

Bundle 是确定性 ZIP：固定 entry 时间、稳定排序、canonical JSON manifest。

```text
manifest.json
files/forge.yaml
files/protocol.json
files/tasks/...
files/logs/audit.jsonl
files/...
```

Manifest 为每个文件记录 `path`、`size`、`sha256`。硬边界：最多 10,000 个文件、单文件 16 MiB、总解压大小 256 MiB。拒绝绝对路径、`..`、反斜线、重复 ZIP entry、manifest 外文件、symlink、size/hash 不一致和未来协议版本。

Export 前必须通过只读 Integrity Scan。Export 不包含 `.forge/exports/` 与临时 lock/tmp 文件，也不包含源码、`.git` 或 SDK 凭证。

## 3. Import authority

```text
verify entire archive
  → create workspace-local staging directory
  → extract only manifest-declared paths
  → rebind forge.yaml project.root
  → atomic rename staging to .forge
  → ensure additive layout
  → append bundle.imported audit evidence
```

目标存在 `.forge` 时 fail closed，禁止 merge/overwrite。导入后 Project ID 与所有业务对象保持不变；只有机器相关的绝对 workspace root 被重新绑定。

## 4. Release gates

`forge release check` 运行六项 gate：release manifest、四个 canonical fixtures、migration current、Evidence Integrity、domain readback、Operator assets。结果写入 `.forge/release/checks/` 并追加 `release.readiness_checked`。Release gate 失败不会修改对象以“修复”结果。

## 5. Operator governance

- Memory 仍为 `DRAFT → ACCEPTED/REJECTED` 人工决策，revision 防止 stale write。
- Policy 只允许项目级 `DENY`。built-in 规则不可通过 UI 或 CLI 退役。
- 项目 Policy 退役记录进入 `.forge/policies/retired/`，保留 actor、reason、timestamp。
- Audit API 支持 Task ID、exact Event Type、Actor、after-sequence cursor；limit `1..200`。
- Web 继续只监听 `127.0.0.1`，使用 session token、CSP、请求体限制和 Codex `deny_all` 默认策略。
