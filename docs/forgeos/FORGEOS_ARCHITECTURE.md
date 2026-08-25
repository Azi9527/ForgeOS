# ForgeOS Integration Architecture

## 1. 推荐总体架构

根据当前 Codex 的 App Server、Extension API、Hooks 和 ThreadStore 结构，目标架构调整为：

```text
Human / CI / IDE
  │
  ▼
Forge Control Plane
  ├─ Python Service / Library API（主入口）
  ├─ forge CLI（单次管理与诊断）
  ├─ ForgeProject / ForgeConfig
  ├─ ForgeTask + TaskStateMachine
  ├─ Workflow / Validation / Review
  └─ Audit / Acceptance
  │             │
  │ .forge/     │ Codex Python SDK
  ▼             ▼
File Protocol   CodexSdkGateway
                      │
                      ▼
                Codex App Server
  │             ├─ ThreadProcessor / TurnProcessor
  │             └─ ThreadManager
  │                    │
  └──────────────┐     ▼
                 │  Codex Session / Agent Loop
                 │     ├─ Model
                 │     ├─ ToolRouter / Registry
                 │     ├─ Sandbox / Approval
                 │     └─ ThreadStore / Rollout
                 │          │
                 ▼          ▼
          Forge Integration / Existing Hooks
          ├─ Context / TurnInput Contributor
          ├─ Thread / Turn / Tool lifecycle
          ├─ Pre/Post Tool policy hooks
          └─ Stop validation gate
                         │
                         ▼
                      Workspace
```

控制面拥有工程状态，官方 Python SDK 提供多轮 Thread/Turn API，底层 Codex App Server 拥有 runtime 请求与事件。第一阶段不实现原始 JSON-RPC 客户端，也不修改 Codex Core；只有 SDK 公共能力出现明确缺口时才下沉 App Server 或进程内 hook。

## 2. 组件职责

| 组件 | 职责 | V1 存储 |
| --- | --- | --- |
| `forgeos` Python package | Project/Config/Task、工作流、状态机和 service API | 无 Codex Core 依赖 |
| Forge store | 原子读写、锁、版本迁移、审计 append | `.forge/` 文件 |
| `CodexSdkGateway` | SDK 进程生命周期、start/resume/run、结构化运行证据 | Codex ThreadStore + `.forge/` correlation |
| `forge` CLI | 单次 `init/status/task show/doctor` 和调试 | 调用同一 Python service，不承载长生命周期 |
| Forge validation | 验证计划、命令结果、evidence、回归比较 | `.forge/validation/` 与 `.forge/logs/` |
| Audit | append-only 工程事件、脱敏和 evidence reference | `.forge/logs/` |

当前最小实现位于顶层 `forgeos/`，不加入 Cargo/Bazel workspace，不提前拆出大量包。

## 3. `.forge/` File Protocol

需求基线定义的协议布局是：

```text
.forge/
├─ forge.yaml
├─ context/
│  ├─ project.md
│  ├─ architecture.md
│  ├─ modules.md
│  └─ tech-stack.md
├─ rules/
│  ├─ global.md
│  ├─ frontend.md
│  ├─ backend.md
│  └─ testing.md
├─ tasks/
│  ├─ active/
│  ├─ completed/
│  └─ failed/
├─ workflows/
│  ├─ feature.yaml
│  ├─ fix.yaml
│  ├─ refactor.yaml
│  └─ review.yaml
├─ validation/
│  ├─ build.yaml
│  ├─ test.yaml
│  └─ regression.yaml
├─ memory/
│  ├─ decisions/
│  ├─ failures/
│  └─ patterns/
└─ logs/
```

M1 的 `forge init` 创建此稳定目录骨架，但只要求 `forge.yaml`、Task persistence、状态机和 logs/audit skeleton 具有行为；Context、Rules、Workflow、Validation、Memory 的实际能力按后续 milestone 增量启用。`forge.yaml` 保存 `forge.version`、project、Codex runtime、Task ID prefix、repair、validation、git 和 audit 开关，不额外引入第二个工程配置权威文件。

规则：

- 所有可持久对象都有 `schema_version`。
- Task ID 单调分配，Task 当前投影保存在 `tasks/active|completed|failed`，持久化必须原子写入（临时文件 + rename）。
- 变更前验证预期 revision，避免并发覆盖。
- audit append-only；对象文件保存当前投影视图。
- 不保存凭证；大型输出使用 hash + evidence path，不嵌入 task YAML。
- V1 不引入数据库；文件和 Git 是可观察、可恢复的权威载体。

## 4. Task State Machine

需求基线规定的状态机：

```text
CREATED → ANALYZING → PLANNED → IMPLEMENTING → VALIDATING
                                                   │
                                      FAIL → REPAIRING
                                                   │
                                             VALIDATING
                                                   │ PASS
                                                   ▼
                                REVIEWING → ACCEPTING → DONE

Exceptional states: BLOCKED / FAILED / CANCELLED
```

M1 实现完整的状态枚举与合法转换，但最初 CLI 验收路径只需证明创建、持久化、读取和拒绝非法转换。`DONE` 必须要求 validation、review 和 acceptance evidence，不能由 Agent 或 `turn/completed` 直接写入。异常状态的进入/恢复规则必须显式定义，不能用通配转换。

## 5. 代码放置决策

当前采用顶层独立 Python package：

```text
forgeos/
├─ pyproject.toml
├─ src/forgeos/
│  └─ codex_sdk.py
└─ tests/
```

理由：

1. 官方 Python SDK 已管理 App Server 进程和 JSON-RPC，无需重复实现。
2. 不进入 Cargo/Bazel workspace，日常 ForgeOS 开发不触发全量 Rust 构建。
3. 依赖方向始终是 `ForgeOS → openai-codex SDK → Codex Runtime`。
4. 可通过 `CodexConfig.codex_bin` 指向指定源码构建产物，不丢失源码基线能力。
5. 原始 App Server client、Rust Extension API 和 Core patch 全部延后到出现可验证缺口之后。

## 6. CLI 定位

CLI 不是持续运行的控制面。它只提供单次、可组合的管理操作，例如 `forge init`、`forge status`、`forge task show` 和 `forge doctor`。多轮执行、恢复、Validation/Repair 循环由 Python service/library 持有，并复用 Codex thread ID。

## 7. App Server 与 SDK 决策

- **控制面生产入口**：官方 Python SDK。
- **底层运行时接口**：SDK 管理的 App Server stable stdio。
- **一次性入口**：Forge CLI；Codex CLI 仅用于调试/smoke，不承担多轮流程。
- **默认安全策略**：`workspace_write + deny_all`；任何放宽必须由 ForgePolicy 明确决定。
- **深层集成**：原始 App Server 或 Rust Extension API 仅在 SDK 公共 API 无法满足时启用。
- **不采用**：TypeScript SDK 作为主入口、实验性 WebSocket、实验性 Codex Project API 或默认 Core patch。

## 8. Validation / Repair 闭环

```text
ForgeTask IMPLEMENTING
  → Codex Turn reaches Stop
  → ForgeValidation plan executes via governed tool/runtime
      ├─ PASS: evidence → REVIEWING
      │             → ACCEPTING → DONE
      └─ FAIL: evidence → REPAIRING
                    → bounded repair context
                    → same/new Codex Turn
                    → validation again
```

必须有 repair 次数、token、时间和命令预算；达到上限进入 BLOCKED，而不是无限循环。Validation 命令由 Forge config 声明，执行仍受 Codex/host Sandbox 与 Approval 限制。

## 9. 设计约束

- Maximum Reuse：复用 App Server、ThreadStore、tools、Sandbox、Approval、MCP、Hooks。
- Minimum Intrusion：M0 零 Core 修改；M1 domain 优先新增 crate。
- Upstream Friendly：所有上游文件改动进入 Patch Registry；保持单向依赖。
- Harness > Prompt：状态机和 validation 是代码/文件协议，不靠提示词自觉。
- Agent != Authority：Agent 输出不能直接改变接受状态。
- Validation First：任务创建时先声明验收条件，完成门读取机器证据。
