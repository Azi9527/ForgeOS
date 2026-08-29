# ForgeOS Project Domain 与迁移方案

状态：Project Registry V2 与 Lifecycle ID Consolidation 实现基线
目标阶段：Project Lifecycle ID Consolidation
原则：Project 是 ForgeOS 的一级权威对象；Codex thread 是项目拥有的长期开发对话，不再反向充当项目身份。

## 1. 职责边界

### Codex App Server 负责

- thread、turn、item 和实时执行事件；
- 模型请求、工具调用、审批请求和会话恢复；
- Codex rollout 及其兼容语义。

### ForgeOS Gateway 负责

- 项目注册、目录边界、Git 仓库与默认执行配置；
- 项目和 Codex thread 的绑定关系；
- 验证、制品、发布、环境、部署和审计；
- 迁移、权限、修订号和浏览器重连后的权威状态。

浏览器只保存可丢弃的 UI 缓存，不能成为项目或发布治理的权威数据源。

## 2. 权威数据模型

### Project

```text
Project {
  projectId: string                 // 不可变，例如 prj_<uuid>
  schemaVersion: integer
  name: string                      // 可重命名的显示名称
  normalizedRootPath: string        // 平台比较使用
  rootPath: string                  // 操作系统原始展示路径
  repositoryRoot: string | null
  repositoryRemote: string | null
  status: active | archived
  defaultProfileId: string | null
  defaultModel: string | null
  lastConversationId: string | null
  createdAt: unix milliseconds
  updatedAt: unix milliseconds
  revision: integer
}
```

### ProjectConversation

```text
ProjectConversation {
  projectId: string
  threadId: string
  profileId: string
  cwd: string
  state: active | archived | detached
  attachedAt: unix milliseconds
  lastOpenedAt: unix milliseconds
}
```

### Engineering Delivery Chain

以下对象全部使用 `projectId`，名称只能作为显示字段：

```text
Conversation / Turn
  -> ChangeSet(repository, branch, commit, diffDigest)
  -> ValidationRun(commit, checks, evidenceDigest)
  -> Artifact(commit, validationRunId, sha256, signature)
  -> Release(artifactIds, approvals, targetEnvironmentId)
  -> Deployment(releaseId, environmentId, status, evidence)
  -> ProjectAuditEvent(actor, action, target, result)
```

## 3. 必须保持的约束

1. `projectId` 创建后不可改变，项目重命名不迁移身份。
2. 一个活跃 thread 在同一 profile 下最多归属一个项目。
3. 新建项目默认创建 `父目录/项目名称`，项目名等于文件夹名。
4. thread 的执行 `cwd` 必须位于项目根目录内；历史外部 worktree 必须以显式关联记录存在。
5. 项目目录、Git 仓库和生命周期数据必须由网关校验，不能信任浏览器传入的派生状态。
6. 发布、部署和审批只接受当前项目中的对象引用。
7. 项目移除默认只解除 ForgeOS 纳管，不删除源码、Codex rollout、制品或远端资源。
8. 所有写操作携带 `revision`，冲突返回可恢复的最新状态。

## 4. 本地项目清单

新项目继续创建：

```text
<project-root>/.forgeos/project.json
```

建议结构：

```json
{
  "schemaVersion": 2,
  "projectId": "prj_...",
  "name": "WebTest",
  "rootPath": "D:\\projects\\WebTest",
  "repositoryRoot": "D:\\projects\\WebTest"
}
```

清单用于识别和恢复项目，不保存凭据、成员权限或发布审批记录。

## 5. 网关持久化

Registry V2 第一阶段复用当前 profile 已具备原子写入、备份恢复和并发锁的
`ui-state.json`，新增独立顶层区域：

```text
projectRegistry
  schemaVersion: 2
  projectsById
  projectIdByThreadId
  migrationCommitsByKey

projectLifecycleById
  <projectId>

projectLifecycleMigration
  schemaVersion: 1
  commitsByProjectId
```

这样可以在不引入第二套数据库或锁协议的情况下先建立稳定 `projectId`，同时继续输出
`sessionFolders` 兼容投影。生命周期对象完成按 `projectId` 迁移后，再按数据量拆分为：

```text
projects-v2/
  registry.json
  <projectId>/
    lifecycle.json
    conversations.json
    audit.jsonl
```

`projectLifecycleByName` 现在只作为旧数据迁移来源保留。所有新的验证、制品、发布、部署和
治理状态都写入 `projectLifecycleById`；制品目录、制品签名域、WebSocket 审计 target 和查询
参数也统一使用 `projectId`。项目显示名称可以修改，但不会触发生命周期数据搬迁。

## 6. API 方向

```text
project/list
project/get
project/create
project/update
project/archive
project/import/preview
project/import/commit
project/conversation/list
project/conversation/attach
project/conversation/detach
projectLifecycle/get
projectLifecycle/migration/get
projectLifecycle/migration/commit
projectLifecycle/migration/rollback
projectLifecycle/migration/recover
```

当前方法通过网关 WebSocket RPC 暴露；`project/list` 支持游标分页。文件系统路径由网关规范化并验证 allowed roots。

当前已实现：项目列表、读取、创建、更新、归档，项目导入预览/提交，对话显式绑定，以及
生命周期 ID 化。生命周期迁移采用“预览冲突 → 写入恢复日志 → 复制并重新签名旧制品 →
原子切换 ID 状态”的流程；迁移中断时可恢复，迁移后未产生新写入时可回滚。

## 7. 现有数据迁移

### 数据来源

- 已纳管 `sessionFolders`；
- session tag；
- thread `cwd`；
- Git repository path；
- `.forgeos/project.json`；
- `projectLifecycleByName`。

### 分类规则

1. 已纳管且有唯一 rootPath：自动生成迁移候选。
2. 只有 cwd 的自动发现项目：显示为“待纳管”，不静默创建。
3. 只有 tag、没有根目录：要求选择或确认目录。
4. 同名不同目录、同目录多名称、一个 thread 多项目标签：标记冲突，禁止自动提交。
5. 已存在 V2 清单：以 `projectId` 为准，旧名称成为临时别名。

### 两阶段迁移

#### Preview

- 展示新 `projectId`、项目名称、根目录和 Git 仓库；
- 展示将迁移的 thread、验证、制品、发布和环境数量；
- 展示冲突、越界 cwd 和缺失目录；
- 不写文件、不修改 tag、不移动源码。

#### Commit

- 使用迁移操作 ID 保证幂等；
- 写入 registry 和项目清单；
- 将 thread 与 `projectId` 建立显式关系；
- 将 `projectLifecycleByName` 复制到项目 ID；
- 保留原数据和名称别名，生成审计事件；
- 任一步失败时恢复迁移前快照。

### 生命周期冲突策略

- `preferLegacy`：以选定的旧名称记录为准，复制旧制品到 `projectId` 目录，并在校验旧摘要与
  签名后以 V2 `projectId` 签名域重新签名；
- `keepCurrent`：保留当前 ID 记录，只登记旧来源已处理；
- 多个名称别名都存在旧数据时必须由操作者明确选择来源，不静默合并；
- 迁移日志处于 `copying` 时界面显示“恢复未完成迁移”；
- 回滚前校验生命周期 revision，迁移后已有新写入时拒绝回滚，防止丢失新数据。

## 8. 兼容与回滚

- 不改写 Codex rollout 历史。
- 不移动现有项目目录。
- 不自动删除旧 SessionFolder 和 tag。
- 迁移记录保存原名称、原目录和原生命周期键。
- 回滚恢复迁移前的 ID 生命周期快照；若迁移前没有 ID 数据则移除该 ID 记录。
- 旧名称状态和旧制品始终保留，回滚不删除源码、对话或审计日志。
- 审计日志保持追加写，不重写历史名称记录；按项目查询时由网关使用项目别名兼容读取，
  所有新审计记录以 `projectId` 作为 target。

## 9. 下一阶段验收标准

1. 项目中心可以准确区分“已纳管项目”和“待纳管目录”。
2. 当前 11 个发现项目能够生成无写入的迁移预览。
3. APS 迁移后获得稳定 `projectId`，刷新、重启和重命名后保持不变。
4. APS 的长期对话、验证、制品、发布、环境和审计均通过 `projectId` 查询。
5. 同名目录、Windows 扩展路径前缀、大小写差异和 worktree 均有测试。
6. 迁移失败可回滚，不删除项目文件或 Codex 历史。
7. 浏览器 `localStorage` 清空后，项目及生命周期仍可完整恢复。
