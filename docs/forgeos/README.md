# ForgeOS M0 Architecture Baseline

本目录记录 ForgeOS 在 OpenAI Codex 当前源码上的 M0 架构基线。ForgeOS 的定位是 **AI Native Software Engineering Harness built on OpenAI Codex Runtime**：Codex 提供 Agent 能力，ForgeOS 负责让工程过程可定义、可验证、可审计和可恢复。

## 基线

| 项目 | 值 |
| --- | --- |
| 需求基线 | `ForgeOS_REQUIREMENTS_V1.0.md`，已完整阅读，共 1,904 行 |
| Codex 分支 | `main` |
| Codex 提交 | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| 上游 | `upstream = https://github.com/openai/codex.git` |
| ForgeOS 远端 | `origin` 尚未配置，未提供 ForgeOS 仓库 URL |
| 克隆方式 | `--depth 1` 浅克隆 |
| M0 代码修改 | 无；只新增本目录文档 |

## 需求摘要

1. **产品目标**：在 Codex Runtime 上建立工程控制层，不重新实现 Coding Agent。
2. **V1 范围**：单 Agent 工程闭环；工程、任务、规则、上下文、工作流、验证、回归、评审、审计与文件协议。
3. **Codex Owned**：模型通信、Agent Loop、工具、Shell、编辑、Sandbox、Approval、MCP、基础上下文、会话、CLI/App Server/SDK 基础设施。
4. **ForgeOS Owned**：ForgeProject、ForgeTask、ForgeRules、ForgeContext、ForgeWorkflow、ForgeValidation、ForgeRegression、ForgeReview、ForgeMemory、ForgeAudit、ForgePolicy。
5. **V1 非目标**：复杂 Multi-Agent、Model Router、Web Console、SaaS/Fleet、向量数据库/RAG、大型数据库和自动化 DevOps 平台。
6. **M0 目标**：确认源码与基线，建立真实架构和执行链，选择扩展点，明确边界与上游策略，设计 M1。
7. **架构原则**：Maximum Reuse、Minimum Intrusion、Upstream Friendly、Harness > Prompt、Agent != Authority、Validation First。

## 构建与运行基线

修改前工作树干净。官方 `docs/install.md` 要求 Windows 11 使用 WSL2；当前主机只有停止状态的 `docker-desktop` WSL2 实例，没有 Linux 开发发行版，也没有 `rustc`、`cargo`、`rustup`、`just`、`cargo-nextest` 或 MSVC Build Tools。因此以下命令均为 **NOT RUN — ENVIRONMENT BLOCKED**，不是源码失败：

```text
cd codex-rs
cargo build
cargo run --bin codex -- "Implement feature X"
just fmt-check
just clippy
just test -p codex-tui
just test
```

已确认的官方工具链是 Rust `1.95.0`，格式化入口是 `just fmt`/`just fmt-check`，测试入口必须是 `just test` 而不是直接执行 `cargo test`。M0 架构研究可完成，但可执行构建基线在配置受支持的 WSL2 Rust 环境后仍需补跑。

| Baseline item | Status | Evidence / intended command |
| --- | --- | --- |
| Build | NOT RUN — ENVIRONMENT BLOCKED | `cargo build` |
| Run | NOT RUN — ENVIRONMENT BLOCKED | `cargo run --bin codex -- "Implement feature X"` |
| Format check | NOT RUN — ENVIRONMENT BLOCKED | `just fmt-check` |
| Lint | NOT RUN — ENVIRONMENT BLOCKED | `just clippy` |
| Targeted tests | NOT RUN — ENVIRONMENT BLOCKED | `just test -p codex-tui` |
| Full tests | NOT RUN — ENVIRONMENT BLOCKED | `just test` |
| Document static checks | PASS | 交付物集合、源码路径、Markdown 链接/围栏、尾随空白 |

环境记录：Windows/PowerShell，Git `2.47.1.windows.1`，Python `3.10.0`，Node `22.16.0`，npm `11.13.0`，`rg` `15.2.0`。官方所需 Rust/Just/nextest 工具不可用；磁盘约有 52.86 GB 可用。Baseline commit 是 `068c49f075cf287a1fe7d1ee36cf005efac922e7`。

## 交付物

- [Codex 架构地图](CODEX_ARCHITECTURE.md)
- [Codex 真实执行链](CODEX_EXECUTION_FLOW.md)
- [ForgeOS 扩展点](EXTENSION_POINTS.md)
- [ForgeOS 集成架构](FORGEOS_ARCHITECTURE.md)
- [Codex / ForgeOS 边界](BOUNDARY.md)
- [上游同步策略](UPSTREAM_STRATEGY.md)
- [上游 Patch Registry](UPSTREAM_PATCHES.md)
- [许可证合规](LICENSE_COMPLIANCE.md)
- [V1 路线图与 M1 计划](V1_ROADMAP.md)
- [下一阶段 N1 执行与工程证据计划](NEXT_STAGE_PLAN.md)
- [N1 验收报告](N1_VALIDATION_REPORT.md)
- [N2 Validation & Report 开发计划](N2_DEVELOPMENT_PLAN.md)
- [N2 验收报告](N2_VALIDATION_REPORT.md)
- [N3 Engineering Memory & Policy 开发计划](N3_DEVELOPMENT_PLAN.md)
- [N3 Memory & Policy 协议](MEMORY_POLICY_PROTOCOL.md)
- [N3 验收报告](N3_VALIDATION_REPORT.md)
- [N4 Operational Hardening 开发计划](N4_DEVELOPMENT_PLAN.md)
- [N4 Operational Protocol](N4_OPERATIONAL_PROTOCOL.md)
- [N4 验收报告](N4_VALIDATION_REPORT.md)
- [N5 Release Readiness 开发计划](N5_DEVELOPMENT_PLAN.md)
- [N5 Release / Bundle Protocol](N5_RELEASE_PROTOCOL.md)
- [N5 验收报告](N5_VALIDATION_REPORT.md)
- [R1 Release Candidate 与分发计划](R1_RELEASE_PLAN.md)
- [R1 Release Checklist](R1_RELEASE_CHECKLIST.md)
- [R1 本地验证与远端 Gate 报告](R1_VALIDATION_REPORT.md)
- [V1.1 Real Project Pilot & Operator UX 开发计划](V1_1_DEVELOPMENT_PLAN.md)
- [V1.1 Real Project Pilot 证据](V1_1_PILOT_EVIDENCE.md)
- [V1.1 验收报告](V1_1_VALIDATION_REPORT.md)
- [ForgeOS 详细开发规范](DEVELOPMENT_STANDARDS.md)
- [ForgeOS 详细开发计划](DEVELOPMENT_PLAN.md)
- [Python SDK 纵向切片验证报告](VALIDATION_REPORT.md)
- [本地 Web Control Developer Preview](UI_DEVELOPER_PREVIEW.md)

## 需求假设与当前源码的差异

| 编号 | 差异 | 处理 |
| --- | --- | --- |
| C-01 | 需求将 Hook 视为待确认能力；当前源码已有命令/MCP/Prompt/Agent Hooks 和类型化 Extension API。 | 优先复用现有机制，不在 M0 设计通用 `RuntimeHook` 替代品。 |
| C-02 | 需求概念图将完成简化为“Agent Finished → Final Response”。 | 以真实的采样循环、Stop hook、`SessionTask` 和 `TurnComplete` 链为准，保留需求中的独立验证语义。 |
| C-03 | 当前 App Server 已有实验性 Project、Goal、Memory、Review 和 Multi-Agent 能力。 | 把它们视为可复用机制；Forge 同名能力仍拥有工程治理和验收语义。 |
| C-04 | 仓库规则通常禁止在 `docs/` 增加产品文档。 | 用户明确要求 M0 文档位于 `docs/forgeos/`，该更具体要求优先；不修改官方 Codex 文档。 |
| C-05 | 当前 TypeScript SDK 调用 CLI，Python SDK 直接调用 App Server；TUI 与 exec 也已使用 App Server。 | 2026-08-24 决策：ForgeOS 首先集成 Python SDK；App Server 保持底层实现，CLI 仅用于单次任务和诊断。 |
| C-06 | M0 要求 Build/Run，但当前 Windows 主机缺少受支持工具链。 | 明确记录环境阻塞，不把未执行伪装为通过，也不通过降低安全或跳过测试解决。 |
