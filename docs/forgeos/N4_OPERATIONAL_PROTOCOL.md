# ForgeOS N4 Operational Protocol v1

## 1. Layout

```text
.forge/
├─ protocol.json
├─ budget/evaluations/<task-id>/<budget-id>.json
├─ recovery/
│  ├─ cancellations/<task-id>.json
│  └─ runs/<recovery-id>.json
├─ integrity/scans/<integrity-id>.json
└─ migrations/<migration-id>.json
```

旧项目只补建目录和 `protocol.json`；现有对象不改写。新项目初始化时直接写当前 protocol manifest。

## 2. Budget

`execution.attempt_limit` 默认 8，允许 1–100。每次 evaluation 保存 Task revision、Attempt used/limit/remaining、repair used/limit/remaining 和 canonical input hash。执行 Attempt 达到 limit 时：

```text
budget.exhausted audit
→ no baseline / no Codex
→ Task BLOCKED
```

Repair budget 继续由状态机和 `repair.limit` 控制；N4 将其消费量纳入同一 evidence projection。

## 3. Cancellation

CancellationRequest 为单 Task 单文件投影：

```text
REQUESTED(revision 0) → APPLIED(revision 1)
```

仅人类 authority 可请求；Agent、Codex、model、assistant、system、ForgeOS automation 和 validation identity 均拒绝。请求使用专用文件锁并幂等返回已有 REQUESTED。无活动 Job 时立即转为 CANCELLED；有活动 Turn 时先调用官方 interrupt，execution 收到结果后应用；validation 中途请求则在当前 validator 返回后的安全边界应用。

取消不删除 Attempt、Validation 或 Git evidence。CANCELLED 为 Task terminal state。

## 4. Startup recovery

启动和显式 `recover` 执行：

1. 读取所有 QUEUED/RUNNING/INTERRUPTING Attempt。
2. 原子标记 INTERRUPTED，错误说明进程未到 terminal state。
3. 若存在 pending Cancellation，将 Task 转 CANCELLED 并应用请求。
4. 否则将非 terminal、非 BLOCKED Task 转 BLOCKED，保留 `blocked_from`。
5. 保存 RecoveryReport：Attempt IDs、blocked/cancelled Task IDs 和 warnings。

Recovery 不自动 resume Codex、不执行 validation、不修改 Git。

## 5. Integrity Scan

扫描项：

- `.forge` 下 symlink、JSON object/schema version、单文件 2 MiB 上限、残留 tmp/lock；
- Task 和 ExecutionAttempt 可解析性；
- Audit JSONL 连续 sequence；
- Memory content hash；
- Policy schema 和 additive DENY；
- Task `validation.report_id`、`regression_report_id`、`task_report_id` 目标存在；
- Memory source Task 存在。

ERROR 导致 `passed=false`；残留 work file 是 WARNING。持久化扫描写 record 和 `integrity.scan_completed` Audit；Doctor 运行 read-only scan，不写状态。

## 6. Migration

`protocol.json` 当前 `protocol_version=1`。`migrate status` 只规划；`migrate apply` 才写入。迁移只允许向当前版本前进；遇到未来版本 fail closed，不做自动 downgrade。每次 apply 保存 from/to/actions 和 Audit。

## 7. Product surfaces

```text
forge budget <task>
forge cancel <task> --requested-by <human> --reason <text>
forge integrity scan
forge migrate status|apply
forge recover
```

Loopback HTTP 提供对应 token-protected endpoints。UI 显示 Budget、Cancellation/Recovery、Integrity、Migration，并提供完整性扫描、必要时应用迁移和取消任务操作。
