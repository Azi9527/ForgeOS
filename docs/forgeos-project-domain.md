# ForgeOS Project Domain 与迁移方案

状态：阶段一设计基线  
目标阶段：Project Domain Consolidation  
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

迁移完成前继续读取现有 `sessionFolders` 和 `projectLifecycleByName`；所有新项目身份和对话
归属写入 V2，同时维护 V1 兼容投影。稳定一个发布周期后再停止 V1 写入。

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
project/lifecycle/get
```

当前方法通过网关 WebSocket RPC 暴露；`project/list` 支持游标分页。文件系统路径由网关规范化并验证 allowed roots。

第一阶段已实现：项目列表、读取、创建、更新、归档，迁移预览/提交，以及对话显式绑定、
解绑和列表。`project/lifecycle/get` 仍沿用名称兼容层，属于下一阶段的生命周期 ID 化工作。

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

## 8. 兼容与回滚

- 不改写 Codex rollout 历史。
- 不移动现有项目目录。
- 不自动删除旧 SessionFolder 和 tag。
- 迁移记录保存原名称、原目录和原生命周期键。
- 回滚仅移除 V2 绑定并恢复 V1 投影，不删除迁移期间产生的源码和对话。

## 9. 下一阶段验收标准

1. 项目中心可以准确区分“已纳管项目”和“待纳管目录”。
2. 当前 11 个发现项目能够生成无写入的迁移预览。
3. APS 迁移后获得稳定 `projectId`，刷新、重启和重命名后保持不变。
4. APS 的长期对话、验证、制品、发布、环境和审计均通过 `projectId` 查询。
5. 同名目录、Windows 扩展路径前缀、大小写差异和 worktree 均有测试。
6. 迁移失败可回滚，不删除项目文件或 Codex 历史。
7. 浏览器 `localStorage` 清空后，项目及生命周期仍可完整恢复。
