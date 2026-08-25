# Upstream Strategy

目标是在长期同步 OpenAI Codex 的同时，让 ForgeOS patch 数量少、职责窄、冲突可审计。

## 1. 当前 Remote 状态

```text
upstream  https://github.com/openai/codex.git
origin    NOT CONFIGURED
branch    main
commit    068c49f075cf287a1fe7d1ee36cf005efac922e7
clone     shallow (--depth 1)
```

提供 ForgeOS 仓库 URL 后再执行：

```bash
git remote add origin <FORGEOS_REPOSITORY_URL>
```

不要把 `origin` 指回 OpenAI 仓库，也不要在没有 URL 时猜测远端。首次需要完整历史分析、merge-base 或长期同步前：

```bash
git fetch --unshallow upstream
```

## 2. 分支与同步模型

推荐：

- `main`：ForgeOS 可发布主线，跟踪 `origin/main`。
- `upstream/main`：OpenAI Codex 只读跟踪分支。
- `forge/mN-*`：短生命周期功能分支。
- `sync/upstream-YYYYMMDD`：上游同步与冲突解决分支。

长期主线采用 **merge upstream/main**，保留每次上游集成边界和冲突决策：

```bash
git fetch upstream
git switch -c sync/upstream-YYYYMMDD main
git merge --no-ff upstream/main
# build/test/Forge regression
git switch main
git merge --no-ff sync/upstream-YYYYMMDD
```

仅对尚未发布、未被他人基于其开发的短功能分支使用：

```bash
git rebase upstream/main
```

不重写已发布 ForgeOS 主线历史。每次同步必须独立 commit/PR，不能和 Forge feature 混在同一提交。

## 3. 文件修改策略

| 类别 | 策略 |
| --- | --- |
| 新增顶层 `forgeos/` Python package | 优先，ForgeOS 自有实现；不触碰 upstream workspace manifest。 |
| `.forge/` protocol/schema/examples | ForgeOS Owned；避免放到 Codex config schema。 |
| `docs/forgeos/` | ForgeOS 架构与 patch 文档；不改写官方 Codex 文档。 |
| `codex-rs/Cargo.toml`, Bazel/lock | 当前不改；只有经验证的 Rust integration gap 才可提案。 |
| `app-server/src/extensions.rs` | 当前不改；Python SDK 不足且替代方案失败后才可提案窄化 patch。 |
| `ext/extension-api` | 仅当现有 Contributor 无法表达经验证的需求；优先通用且向后兼容的窄 API。 |
| `core/src/session/turn.rs` | 高风险；只有 Stop hook 证据不足时才允许 completion gate 调用点。 |
| CLI/TUI、protocol、config | 尽量不改；如需改动遵守稳定 API/schema/snapshot 规则。 |
| Sandbox、Approval、MCP、Auth、model client | 默认禁止 Forge patch；复用原能力，安全修复单独评估。 |

## 4. Patch 生命周期

任何上游拥有文件的 Forge 改动在编码前：

1. 在 `UPSTREAM_PATCHES.md` 分配 ID 和 owner。
2. 写清无法用新增文件/extension/hook/App Server 达成的证据。
3. 限制变更到一个职责和最少调用点。
4. 添加行为测试；Agent loop 改动使用 `core/suite` 集成测试，App Server 改动使用公开 JSON-RPC 测试。
5. 运行受影响 crate 的 `just test -p ...`；core/common/protocol 改动再经批准运行完整 `just test`。
6. 同步上游时逐项验证 patch 仍然必要；上游已提供替代时删除本地 patch。

Patch 状态使用 Proposed、Active、Superseded、Dropped、Upstreamed。每次冲突解决更新 last-verified upstream commit。

## 5. 冲突处理

冲突优先级：

1. 理解上游新的行为、测试和安全约束。
2. 检查 patch 的原始需求是否已被上游 API 满足。
3. 若已满足，删除 Forge patch，迁移 integration。
4. 若仍需 patch，在新上游结构中重新实现最小语义；不机械选择 ours。
5. 更新架构图、Patch Registry 和 regression evidence。

特别关注高冲突热点：CLI Clap 定义、`MessageProcessor`、`app-server/src/extensions.rs`、`ThreadManager`、`session/turn.rs`、tool registry、config schema 和 app-server protocol。

## 6. Upstream Acceptance Reality

当前 `docs/contributing.md` 表明 OpenAI Codex 不接受常规外部代码贡献/PR。ForgeOS 的 “Upstream Friendly” 主要意味着：

- 易于持续拉取上游；
- patch 容易理解、删除或重做；
- 不冒充上游已接受的 API；
- 通过 issue/design channel 报告通用问题，而不是假设能合并 Forge 特性。

如果贡献政策改变，再评估将真正通用的 Extension API 能力上游化。

## 7. 同步验收清单

- upstream commit、sync commit 和所有冲突文件已记录。
- `UPSTREAM_PATCHES.md` 中 Active patch 逐项复验。
- Cargo/Bazel locks 和生成 schema 无漂移。
- format、build、受影响测试、lint 通过。
- Forge task persistence/state transitions 通过。
- completion gate PASS/FAIL/repair/abort/resume regression 通过。
- Sandbox/Approval 不弱化。
- `.forge/` schema 向后兼容或有显式 migration。
