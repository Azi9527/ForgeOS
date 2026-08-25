# Codex / ForgeOS Boundary

边界的核心判断是：Codex 拥有“Agent 如何工作”的运行机制，ForgeOS 拥有“工程工作为何开始、何时可接受、证据如何保留”的治理语义。

## Codex Owned

- Agent Runtime、模型通信、采样循环和 tool calling。
- Shell、Apply Patch、文件操作、搜索和命令执行。
- 平台 Sandbox、文件/网络边界和命令限制。
- Approval、Guardian、危险命令分类和权限升级协议。
- MCP client/server、动态工具、Skills/Plugins 基础设施。
- Base/System/Developer context、AGENTS.md、history、compression。
- Thread、Session、Turn、rollout persistence 和 resume。
- CLI、TUI、exec、App Server、protocol 和 SDK 基础设施。
- Authentication、model config、Codex project config。
- 原生 Review/Goal/Memory/Multi-Agent 等可复用运行能力。

ForgeOS 不重写这些能力，也不通过包装层降低其安全语义。

## ForgeOS Owned

- **ForgeProject**：工程治理单元、schema、仓库身份和工程配置。
- **ForgeTask**：有验收条件、证据和状态机的工程工作项。
- **ForgeRules / ForgePolicy**：工程约束、验证要求、风险规则；只能收紧运行权限。
- **ForgeContext**：从工程事实选择、裁剪、版本化的上下文。
- **ForgeWorkflow**：任务阶段、修复循环和门禁编排。
- **ForgeValidation**：独立于 Agent 自我陈述的 build/test/lint/自定义检查。
- **ForgeRegression**：基线与变更后结果比较。
- **ForgeReview**：对 diff、风险和证据的接受门。
- **ForgeMemory**：经过接受、可追溯、可失效的工程知识。
- **ForgeAudit**：不可混淆的事件、证据引用、操作者和决策记录。
- **Acceptance**：唯一能将 ForgeTask 置为 DONE 的工程权威。

## 重叠能力的语义处理

| 名称重叠 | Codex 语义 | ForgeOS 语义 | 处理 |
| --- | --- | --- | --- |
| Project | App Server 的项目分组/运行配置，部分 API 实验性 | 可版本化的工程治理身份 | M1 不依赖实验性 Project API；通过映射 ID 关联。 |
| Task/Turn | 一次 runtime 工作/用户到终态的 Turn | 跨多个 Turn、验证和修复的工程工作项 | `forge_task_id` 可关联多个 thread/turn；状态不可由 TurnCompleted 直接设置 DONE。 |
| Rules/Policy | Codex config、exec policy、Sandbox、approval | 工程范围和过程约束 | Forge 只增加限制；Codex safety 始终保留最终机械执行权。 |
| Context | 模型 prompt/history/world state | 工程事实的选择与生命周期 | Forge 通过 Contributor 注入有界 fragment，不拥有或重写 ConversationHistory。 |
| Validation | Codex 可执行测试/命令 | 独立判定和证据模型 | 复用 Shell 执行，但命令集、结果解析和 PASS/FAIL 权威属于 Forge。 |
| Review | Codex review task/能力 | 验收阶段和状态门 | 可调用 Codex Review 产出意见；Forge Acceptance 决定状态。 |
| Memory | Codex 会话/实验性 memory | 已接受且带来源、版本和失效规则的工程知识 | 不直接把未经审查的模型记忆提升为 ForgeMemory。 |
| Audit | Codex rollout/event/telemetry | 工程决策链和证据索引 | 引用或摘要 Codex 事件，敏感信息脱敏；不复制所有 transcript。 |
| Completion | Codex TurnCompleted | ForgeTask DONE | 两个状态机完全分离，通过 completion gate/控制层协调。 |

## Authority Model

```text
Agent proposes work and a final message
  ↓
Codex enforces runtime safety and emits TurnCompleted
  ↓
ForgeValidation evaluates declared checks and evidence
  ↓
ForgeReview evaluates diff/risk
  ↓
Acceptance policy or authorized human
  ↓
ForgeTask = DONE
```

任何模型文字（包括“tests pass”“done”）都只是 claim。只有由 ForgeOS 直接观察的 exit code、报告、Git diff、review 决策及接受事件才是状态机证据。

## Dependency Boundary

依赖只允许朝向：

```text
forgeos domain/service (no codex-core dependency)
  ↑
CodexSdkGateway / forge-validation
  ↑
openai-codex Python SDK
  → Codex App Server / Runtime
```

`codex-core` 不反向依赖 Forge domain。第一阶段不安装 Forge extension；Python SDK 公共 API 出现经验证的缺口后，才评估 App Server composition。不要把 ForgeProject/ForgeTask 类型灌入 Codex Session 核心。
