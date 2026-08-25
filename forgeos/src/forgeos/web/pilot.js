(() => {
  const escape = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[char]);

  function taskGuidance(task, activeJob, hasReport) {
    if (activeJob?.kind === "run") {
      return { tone: "running", title: "观察当前 Codex Turn", detail: "可发送补充约束；发现方向错误时可安全中断。" };
    }
    if (activeJob?.kind === "validate") {
      return { tone: "running", title: "等待独立验证完成", detail: "验证结果会决定进入审核或返回修复。" };
    }
    if (["CREATED", "IMPLEMENTING", "REPAIRING"].includes(task.status)) {
      return { tone: "ready", title: "运行 Codex", detail: "ForgeOS 将记录基线、上下文、执行过程和变更证据。" };
    }
    if (task.status === "VALIDATING") {
      return { tone: "ready", title: "执行 Validation", detail: "独立验证通过前，Agent 的完成声明不会成为 DONE。" };
    }
    if (task.status === "REVIEWING") {
      return { tone: "human", title: "进行人工 Review", detail: "检查架构、质量、风险、测试、兼容性和技术债。" };
    }
    if (task.status === "ACCEPTING") {
      return { tone: "human", title: "逐项最终验收", detail: "只有具名的人类验收者可以把任务推进到 DONE。" };
    }
    if (task.status === "BLOCKED" && task.blocked_from === "VALIDATING") {
      return { tone: "blocked", title: "修复验证阻塞", detail: "查看失败证据后重试 Validation；不要跳过失败检查。" };
    }
    if (task.status === "BLOCKED") {
      return { tone: "blocked", title: "检查阻塞证据并恢复", detail: "确认预算、取消、运行错误或策略原因后重试 Codex。" };
    }
    if (task.status === "DONE" && hasReport) {
      return { tone: "done", title: "下载最终 Task Report", detail: "任务已完成，可导出可审计的工程报告。" };
    }
    if (task.status === "DONE") {
      return { tone: "blocked", title: "补全历史任务报告", detail: "该任务早于报告机制完成；保留现有审计证据，新任务会在验收时自动生成报告。" };
    }
    if (["FAILED", "CANCELLED"].includes(task.status)) {
      return { tone: "blocked", title: "保留证据并创建后续任务", detail: "终态不会被静默重开；使用现有证据建立新的修复任务。" };
    }
    return { tone: "blocked", title: "检查任务证据", detail: "当前状态没有自动操作，请确认最近 Audit 与 Execution Attempt。" };
  }

  function renderBootstrap(doctor) {
    const target = document.getElementById("bootstrap-readiness");
    if (!target) return;
    const checks = doctor?.checks || [];
    target.innerHTML = checks.map((check) => `
      <span class="readiness-item ${escape(check.status.toLowerCase())}">
        <strong>${escape(check.name)}</strong>${escape(check.detail)}
      </span>`).join("");
  }

  function renderWorkspace(status, doctor, tasks) {
    const panel = document.getElementById("pilot-panel");
    if (!panel) return;
    panel.classList.remove("hidden");
    const checks = doctor?.checks || [];
    const failures = checks.filter((check) => check.status === "FAIL");
    const warnings = checks.filter((check) => check.status === "WARN");
    const ready = failures.length === 0;
    const badge = document.getElementById("readiness-badge");
    badge.textContent = ready ? (warnings.length ? "WARN" : "PASS") : "FAIL";
    badge.className = `readiness-badge ${ready ? (warnings.length ? "warn" : "pass") : "fail"}`;
    document.getElementById("readiness-title").textContent = ready ? "工程运行条件已就绪" : "先修复环境阻塞";
    const next = failures[0]
      ? `修复 ${failures[0].name}：${failures[0].detail}`
      : tasks.length === 0
        ? "下一步：创建第一个 ForgeTask，写清目标和可验证的验收条件。"
        : "下一步：选择一个任务，ForgeOS 会显示该状态唯一推荐的操作。";
    document.getElementById("pilot-next").textContent = next;
    document.getElementById("pilot-new-task").disabled = !ready;
    document.getElementById("readiness-list").innerHTML = checks.map((check) => `
      <span class="readiness-item ${escape(check.status.toLowerCase())}" title="${escape(check.detail)}">
        <strong>${escape(check.name)}</strong>${escape(check.status)}
      </span>`).join("");
    document.getElementById("project-name").textContent = status.project.name;
  }

  function saveJson(value, filename) {
    const blob = new Blob([`${JSON.stringify(value, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  window.ForgePilot = { renderBootstrap, renderWorkspace, saveJson, taskGuidance };
})();
