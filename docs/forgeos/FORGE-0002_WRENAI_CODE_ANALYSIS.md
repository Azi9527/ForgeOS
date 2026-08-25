# FORGE-0002：WrenAI 代码分析

## 1. 结论摘要

WrenAI 当前 `main` 已不是早期的 Docker 聊天式 BI 应用，而是一个面向 AI Agent 的开放上下文层、语义 SQL 引擎和执行工具箱。它把业务语义沉淀为可版本化的 MDL、规则和已确认的 NL→SQL 样例，由外部 Agent 负责理解自然语言、编排检索和生成 SQL，再由 Wren 做语义展开、策略检查、方言转换和数据库执行。

总体判断：**适合有工程团队、已有 Agent 平台、愿意维护语义模型，并能落实数据库最小权限的场景；不适合作为开箱即用的聊天式 BI 产品直接上线。建议“有条件采用，先做受控 PoC”，不建议把当前最新发布包直接连接到拥有写权限的生产账号。**

采用前有一个必须处理的高风险版本差异：

- 当前源码已在 2026-08-20 的提交 [`ce9513d`](https://github.com/Canner/WrenAI/commit/ce9513d68ae73887ce858940d58fe26b4dda12b7) 中加入输入 SQL 与规划后 SQL 的双重只读校验。
- 最新发布包 `wrenai 0.13.3` 发布于 2026-08-18，其发布提交早于上述修复，因此不包含该只读保护。
- 修复说明明确指出部分连接器使用 `autocommit=True`，漏过的写操作会直接持久化。

因此生产使用必须同时满足：数据库账号本身只读、启用 Wren `strict_mode`、固定到包含 `ce9513d` 的构建或等待后续正式版本，并通过目标数据库的真实驱动测试验证查询边界。

## 2. 分析边界

| 项目 | 边界 |
| --- | --- |
| 仓库 | [`Canner/WrenAI`](https://github.com/Canner/WrenAI) |
| 分支 | `main` |
| 源码基线 | [`f2841bcbdf8daed9cab9bd5d83275bc51c176594`](https://github.com/Canner/WrenAI/tree/f2841bcbdf8daed9cab9bd5d83275bc51c176594)，2026-08-21 |
| 最新 CLI/SDK 发布 | [`wrenai 0.13.3`](https://github.com/Canner/WrenAI/releases/tag/wren-v0.13.3)，2026-08-18 |
| 分析日期 | 2026-08-24 |
| 方法 | 仓库结构、官方架构文档、关键源文件、提交差异、发布记录、CI 与安全策略的静态审查 |

本报告没有克隆或执行上游项目，也没有连接真实数据库，因此不把官方 CI 配置等同于本次独立运行结果。早期 WrenAI GenBI 应用位于 `legacy/v1`（`v1-final`），官方已明确停止功能和安全更新，不属于本报告的代码基线。

## 3. 产品定位

当前 WrenAI 的核心不是“内置 LLM 的自然语言问数应用”，而是供外部 Agent 使用的四层能力：

1. Agent workflow：Markdown skills 规定 onboarding、建模、查询、校验和记忆更新流程。
2. Project context：MDL、业务规则、连接 profile 和已确认查询样例定义业务含义。
3. Planning engine：Python 编排、sqlglot 和 Rust/DataFusion 语义引擎共同把面向模型的 SQL 展开成目标数据库 SQL。
4. Execution layer：连接器在目标数据库执行查询并以 PyArrow 表返回结果。

换言之，外部 Agent 负责“自然语言 → 决策与 SQL”，Wren 负责“业务上下文 → 受治理的可执行 SQL”。这一边界让模型供应商和 Agent 框架可替换，但最终正确性仍取决于 Agent 行为、MDL 质量和业务规则维护，而不是 Wren 单独保证。

官方架构说明见 [`docs/core/reference/architecture.md`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/docs/core/reference/architecture.md)。

## 4. 仓库与模块结构

| 模块 | 技术 | 责任 |
| --- | --- | --- |
| `core/wren-core` | Rust、Apache DataFusion 53 | MDL 分析、逻辑计划、关系/计算字段展开、SQL 生成与优化 |
| `core/wren-core-base` | Rust | Manifest/MDL 公共类型与 builder |
| `core/wren-core-py` | Rust、PyO3、maturin | 向 Python 暴露语义引擎 |
| `core/wren-core-wasm` | Rust、WebAssembly、TypeScript | 浏览器内语义查询和 GenBI dashboard 运行时 |
| `core/wren` | Python 3.11+、Typer、Pydantic、sqlglot、PyArrow | CLI/SDK、项目上下文、profiles、连接器、MCP、memory、GenBI 编排 |
| `core/wren-mdl` | JSON Schema | MDL 结构定义 |
| `sdk/wren-langchain`、`sdk/wren-pydantic` | Python | Agent 框架适配 |
| `skills` | Markdown/脚本 | Agent 工作流说明 |
| `docs/core` | Markdown | 架构和模块文档 |

Rust workspace 的语义核心版本为 `0.3.1`，DataFusion 为 `53`；Python `wrenai` 为 `0.13.3`，项目元数据仍标记为 Beta。多个包独立发版，带来了较清晰的模块边界，也增加了 Python/Rust/WASM 包之间的版本兼容管理成本。

依据：[`core/wren/pyproject.toml`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/pyproject.toml)、[`core/wren-core/Cargo.toml`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren-core/Cargo.toml)。

## 5. 核心查询链路

```text
用户问题
  -> 外部 Agent / Wren skill
  -> 检索 MDL、业务规则和历史 NL→SQL 样例
  -> Agent 生成面向 MDL 对象的 SQL
  -> WrenEngine
       1. sqlglot 解析目标方言 SQL
       2. 检查只读语句、strict mode 和禁用函数
       3. 提取查询涉及的最小 Manifest
       4. wren-core/DataFusion 展开模型、关系和计算字段
       5. CTE rewriter 注入模型 SQL
       6. 再次检查规划后的 SQL
       7. 转换为目标数据库方言
  -> Connector 执行
  -> PyArrow / MCP JSON 结果
  -> 人工确认后可写入 query memory
```

`WrenEngine` 是 Python 主入口。`dry_plan()` 只规划，`dry_run()` 交给数据库验证，`query()` 执行并返回 Arrow 表。Manifest extractor 会尽量只保留当前查询需要的模型；SessionContext 被缓存，以降低重复构建开销；连接器按 datasource 延迟导入，缺少可选依赖时提示安装相应 extra。

关键实现：[`engine.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/engine.py)、[`connector/factory.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/connector/factory.py)、[`connector/base.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/connector/base.py)。

## 6. 上下文、记忆与 Agent 接口

Wren project 把源数据和派生数据分开：

- MDL、`knowledge/rules/*.md`、`knowledge/sql/*.md` 是 Git 可审查的事实源。
- `target/mdl.json` 是编译产物。
- `.wren/memory/` 是可重建的 LanceDB 索引。
- `~/.wren/profiles.yml` 和项目 `.env` 保存环境相关连接信息。

记忆层有 schema context 和 query history 两条检索轴。安装 `memory` extra 后使用 LanceDB 与 sentence-transformers；未安装时 MCP 的查询召回可退回到依赖较少的文本匹配或完整 schema 描述。这个设计优点是知识可审计、索引可重建，不把业务定义锁死在某个 SaaS UI 中。

MCP 服务暴露查询、dry-run、dry-plan、模型/函数/知识读取和可选的 `store_query`。查询工具默认最多返回 1,000 行、硬上限 10,000 行；写入记忆工具只有 `allow_write` 时才注册。相比之下，直接 CLI/SDK 的 `query(limit=None)` 可以不设上限，生产封装应自行强制超时、扫描量和返回行数配额。

依据：[`mcp_server.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/mcp_server.py)、[`wren-langchain README`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/sdk/wren-langchain/README.md)。

## 7. 数据源与交付形态

官方宣称支持 22+ 数据源。Python connector registry 可见 PostgreSQL、MySQL/Doris、SQL Server、Canner、BigQuery、DataFusion、DuckDB/本地与对象存储文件、Redshift、Spark、Databricks、Trino、ClickHouse、Oracle、Snowflake 和 Athena 等映射。多数驱动以 pip extras 独立安装，能降低默认依赖体积，但不同驱动的事务、超时、LIMIT 和 dry-run 语义仍需逐库验证。

主要交付形态：

- `pip install wrenai`：CLI 与 Python SDK，DuckDB 默认可用。
- `pip install "wrenai[postgres,memory,mcp]"`：按需增加连接器、记忆和 MCP。
- `npx skills add Canner/WrenAI`：向 Agent 安装发现 stub/skills。
- `wren serve mcp`：以 stdio 或 HTTP 暴露工具。
- `@wrenai/wren-core-wasm`：在浏览器内查询 JSON/CSV/Parquet，供静态 dashboard 使用。

WASM 约 68 MB 原始大小、约 14 MB gzip；URL 模式要求服务端支持 CORS 和 HTTP Range。它适合小到中等规模的浏览器侧数据集与静态 dashboard，不应被理解为替代数据仓库的大规模执行层。

依据：[`wren-core-wasm README`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren-core-wasm/README.md)。

## 8. 工程质量与测试

正向信号：

- Rust CI 执行 `cargo check`、amd64 测试、主分支 ARM64 测试、Clippy `-D warnings` 和 TOML 格式检查。
- Rust SQL 端到端覆盖使用 sqllogictest，另有 `insta` 快照测试。
- Python CI 分开执行 lint、核心单元测试、PostgreSQL/MySQL 连接器测试、UI、memory 和 MCP 测试。
- PyO3 binding 单独运行 Rust 与 Python 测试；WASM 有构建、TypeScript typecheck、集成测试和 gzip 15 MB 大小门禁。
- 发布采用 release-please，包独立发版；安全策略只承诺维护各包最新 minor。

需要关注：

- 已检查的 Python live connector matrix 只明确列出 PostgreSQL 和 MySQL；其余连接器即使有单元/模拟测试，也未在该 workflow 中看到同等级真实服务验证。
- SDK 与 binding 的常规 CI 主要运行在 Ubuntu/Python 3.11；各数据库驱动在 Windows、macOS、Python 3.12 的组合需自行验收。
- 官方记录了 Rust `ModelAnalyzeRule` 尚不能解析相关子查询中的外层列引用，影响 TPCH Q2、Q4、Q15、Q17、Q20、Q21、Q22。
- LangChain 工具当前为同步调用，文档提示高并发异步服务可能耗尽默认线程池；同一 memory index 重建期间并发读可能瞬时失败。

依据：[`rust.yml`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/.github/workflows/rust.yml)、[`wren-ci.yml`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/.github/workflows/wren-ci.yml)、[`wasm-ci.yml`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/.github/workflows/wasm-ci.yml)、[仓库开发说明](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/.claude/CLAUDE.md)。

## 9. 安全与治理分析

### 9.1 高风险：发布包落后于只读修复

`wrenai 0.13.3` 早于只读查询修复。当前源码使用允许列表接受 `SELECT`、集合操作、子查询和 `VALUES`，遍历 AST 阻止 DDL/DML、`SELECT INTO`、锁和会话状态变更；规划后还会再次检查，防止 MDL view 或 `ref_sql` 注入写操作。但规划后 SQL 若因方言原因无法被 sqlglot 重解析，当前实现选择 fail-open。

处置：数据库账号必须在数据库层只读；不要单靠 SQL AST 校验。若 MDL 来自不可信来源，应把规划后 parse fail-open 视为额外信任边界。

### 9.2 高风险：治理模式默认关闭

`WrenConfig.strict_mode` 默认是 `False`。未启用时，Wren 不要求所有表引用都存在于 MDL；这意味着 Agent 可以绕过语义模型直接读取底层表。只读保护能防写，但不能防止越过业务模型、读取敏感表或产生不一致口径。

处置：生产环境强制启用 strict mode，配置 denied functions，使用只授予允许 schema/view 的数据库角色，并对生成 SQL 与实际访问对象做审计。

### 9.3 中风险：strict mode 的函数边界需要持续维护

strict mode 会阻止已知文件/远程 reader，例如 `read_csv`、`read_parquet`、`dblink` 和外部数据库 scanner，以降低路径遍历、SSRF、数据外带和横向移动风险。源码注释也明确承认：非 source 位置使用的是需按 connector 持续维护的 blocklist，新出现而未枚举的 reader 可能漏过。

处置：升级 sqlglot/数据库驱动时回归安全用例；数据库禁用危险扩展和函数；运行环境限制文件系统与出网。

### 9.4 中风险：记忆污染与知识供应链

确认后的 NL→SQL 可由 Agent 写回 Markdown 和 LanceDB，错误样例会成为后续 few-shot 依据。Skills、MDL、规则和 query memory 都属于可执行决策上下文，需像代码一样评审。

处置：默认关闭 Agent memory write；由人工或 CI 校验后合并知识文件；对变更保留 reviewer、数据集版本和验证证据。

### 9.5 开源与商业边界

`core/**`、`sdk/**`、`skills/**` 和 `examples/**` 为 Apache-2.0，`docs/**` 为 CC BY 4.0，商标另行管理。完整的用户/组访问控制、行列级安全、商业 GenBI UI/嵌入/API、企业审计与 SLA 属于 Cloud/Enterprise 边界。开源引擎可自托管，但不能把它等同于完整的多租户 BI 权限平台。

依据：[`policy.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/policy.py)、[`config.py`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/core/wren/src/wren/config.py)、[`LICENSE`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/LICENSE)、[`SECURITY.md`](https://github.com/Canner/WrenAI/blob/f2841bcbdf8daed9cab9bd5d83275bc51c176594/SECURITY.md)。

## 10. 主要优点

1. 语义层与 Agent 解耦：可替换模型和 Agent 框架，不把 LLM 调用固化在引擎内。
2. 上下文可审查：MDL、规则和成功查询都是 Git 友好文件，便于 code review、回滚和审计。
3. 规划与执行分层：`dry_plan`、`dry_run`、结构化错误为 Agent repair loop 提供明确原语。
4. 跨数据源抽象清晰：统一 Connector 接口，按 extras 安装，查询结果统一为 PyArrow。
5. Rust 核心可复用：Python binding 和 WASM 共享语义逻辑，适合 CLI、MCP、服务端和浏览器多种形态。
6. 工程门禁较完整：核心模块具有 lint、测试、快照、架构矩阵和独立发布流程。

## 11. 主要风险

| 优先级 | 风险 | 影响 |
| --- | --- | --- |
| P0 | 最新发布包早于只读 SQL 修复 | 使用写权限连接时可能发生持久化 DML/DDL |
| P0 | `strict_mode` 默认关闭 | Agent 可绕过 MDL 读取底层表，治理承诺不成立 |
| P1 | 正确性依赖 MDL、规则和外部 Agent | 语义缺失、样例污染或 Agent 错误仍会产生可信外观的错误答案 |
| P1 | OSS 不含完整身份与行列级权限产品层 | 多租户和敏感数据场景需数据库权限或商业能力补齐 |
| P1 | 22+ connector 的真实 CI 深度不一致 | 方言、LIMIT、超时、事务和 dry-run 行为可能因数据库而异 |
| P1 | 多包、跨语言独立发版 | Python/Rust/WASM 兼容和升级回归成本较高 |
| P2 | 已知相关子查询限制 | 部分复杂分析 SQL 无法正确规划 |
| P2 | WASM 体积和 Range/CORS 约束 | 首屏、CDN 与浏览器内大数据处理受限 |
| P2 | 同步 Agent SDK 与索引重建并发限制 | 高并发服务需线程池、隔离和重建策略 |

## 12. 适用与不适用场景

适用：

- 已有 Claude/Codex/Cursor/LangChain/Pydantic AI 等 Agent 运行时，希望补充语义 SQL 工具。
- 数据团队能维护 MDL、指标、关系、业务规则和 golden queries。
- 希望上下文可本地保存、Git 审查并跨 Agent 复用。
- 需要多数据源统一语义层，且愿意对实际使用的数据源做专项 PoC。
- 使用只读数据库角色，并具备查询审计、成本治理和数据脱敏能力。

不适用：

- 期望安装后直接得到旧版聊天式 BI UI、用户体系和 dashboard 管理后台。
- 没有语义建模负责人，只希望 LLM 从裸 schema 自动得到稳定业务口径。
- 需要开源版本原生提供完整多租户、RLS/CLS、审批和企业审计。
- 需要对任意复杂 SQL 或所有 22+ 数据源给出一致 SLA。
- 只需要一次性分析单个 CSV；此时 Wren 的建模和运维成本偏高。

## 13. 建议的 PoC 准入门槛

1. 使用独立只读数据库账号，数据库层验证 DDL/DML 均被拒绝。
2. 固定包含 `ce9513d` 的源码/包；正式发布前不要只依据 `0.13.3` 的版本号。
3. 开启 `strict_mode`，证明未建模表、危险 reader 和禁用函数均不可访问。
4. 选择一个真实业务域，人工维护 10–30 个 golden NL→SQL/结果集用例。
5. 验证 join、计算字段、时间口径、空值、权限、超时、超大结果和相关子查询。
6. 对目标 connector 做真实服务集成测试，不以 PostgreSQL/MySQL CI 代替其他数据库验收。
7. MCP 默认关闭 `allow_write`；知识变更通过 PR 审核后再重建 memory index。
8. 设置查询超时、扫描/费用上限、最大返回行数、日志脱敏和 SQL 审计。
9. 验证 Agent 失败时能通过 dry-plan、dry-run 和结构化错误修复，而不是无限重试。
10. 将升级过程纳入回归：锁定 `wrenai`、`wren-core-py`、sqlglot、驱动和 embedding 模型版本。

## 14. 最终建议

WrenAI 的差异化价值不是又一个 text-to-SQL prompt，而是把“语义、业务知识、成功样例、规划、执行”拆成 Agent 可编排且可审查的基础设施。架构方向合理，尤其适合正在建设企业 Agent 数据工具链的团队。

但当前仍处于快速演进的 Beta 阶段，源码与最新发布包之间已经出现直接影响数据库写安全的时间差，默认配置也不会自动获得完整治理。**建议结论为：技术路线值得 PoC；生产采用需条件批准。在新的正式发布包含只读修复、strict mode 被强制启用、数据库角色只读、目标 connector 通过真实回归之前，不应批准生产直连。**

## 15. 搜索与证据说明

- GitHub OpenCLI 适配器只有登录和身份命令，无法读取仓库，已跳过真实仓库查询。
- Gemini 技术导航检索执行 1 次但超时，未产生可用内容，也未用于任何结论。
- 实际分析证据来自 GitHub 仓库页面、raw 源文件、官方架构文档、提交记录、发布记录、CI workflow、LICENSE 和 SECURITY 文件。
