# ForgeOS 企业 AI 原生平台：第四阶段交付说明

## 阶段目标

把项目生命周期从“可记录”推进到“可交付、可验证、可审批、可追溯”。持续 Codex 对话仍然是开发主路径；制品、发布、部署和审计只在项目内按需展开。

## 已完成

1. GitHub Actions 在 Linux、macOS 和 Windows 构建网关；Windows 作业额外生成可安装 ZIP、独立 SHA-256 文件和 GitHub 构建来源证明。
2. 项目网关提供真实制品文件上传、隔离存储、下载和验证接口；文件名经过约束，上传大小复用网关限制。
3. 上传时由服务端复算 SHA-256，并使用 profile 隔离的 HMAC-SHA256 密钥签署不可变清单。浏览器不能自行声明签名可信。
4. 下载前重新读取文件并验证摘要与签名；篡改后的制品不会被返回。
5. 发布申请绑定目标环境。生产发布要求两名不同操作者审批、至少一名所有者，并强制引用通过服务端签名验证的制品。
6. 环境支持两类部署适配器：项目目录中的显式命令，以及受约束的 `gh workflow run` GitHub Actions 调度。平台不保存 GitHub Token，只使用操作者现有的 `gh` 登录态。
7. 项目发布与运维工作面新增项目审计时间线，汇总验证、制品、发布和部署状态变更。
8. Windows CI 运行生命周期策略测试和网关升级/回滚测试，避免只验证前端构建。

## 安全边界

- HMAC 密钥保存在当前 runtime profile 数据目录，不进入项目生命周期 JSON、制品目录或浏览器。
- 外部部署适配器只接受受限的仓库、工作流、分支和版本字符集，避免将自由文本拼接进命令。
- 部署仍然需要操作者明确点击；本阶段没有引入后台自动生产发布。
- GitHub Actions 凭据由 GitHub CLI 自己管理，ForgeOS 只保存非敏感目标引用。
- 项目审计日志有大小上限和轮转机制，时间线读取也有硬上限。
- ZIP 的 GitHub provenance attestation 证明 CI 构建来源；项目制品的 HMAC 签名用于本机 ForgeOS 信任域，两者职责不同。

## Windows 网关升级包

触发 `Gateway release bundles` 工作流（tag `v*` 或手工执行）后，Windows 作业产出：

```text
forgeos-gateway-<version>-x86_64-pc-windows-msvc/
forgeos-gateway-<version>-x86_64-pc-windows-msvc.zip
forgeos-gateway-<version>-x86_64-pc-windows-msvc.zip.sha256
GitHub build provenance attestation
```

升级器仍会读取包内 `forgeos-gateway.json`，核对目标平台与网关二进制 SHA-256，并保留前一版本用于原子回滚。

## 验证

- `npm run check`：通过，0 errors / 0 warnings。
- `npm run test:gateway-release`：通过，2/2。
- `git diff --check`：通过。
- 本机 Rust 测试：已启动；当前 GNU Rust 工具链缺少 `gcc.exe` / `dlltool.exe`，在第三方 `ring` 构建脚本处停止。Windows CI 使用 MSVC runner 执行新增测试。
- 本机 Rust 格式检查：当前工具链未安装 `rustfmt` component；CI 工具链负责最终验证。

## 下一阶段建议

1. 部署适配器插件化：增加 Kubernetes、SSH Runner 或企业流水线适配器，但凭据仍只保存引用。
2. 审批策略配置化：按项目定义审批人数、角色、审批有效期、维护窗口和紧急变更流程。
3. 制品保留策略：配额、过期清理、发布锁定和外部对象存储适配器。
4. 通知路由：将生产审批、部署结果和回滚事件送往企业 IM 或邮件。
5. 在第二个真实项目完成“验证 → 上传制品 → 双人审批 → 外部部署 → 健康检查 → 审计复盘”试点。
