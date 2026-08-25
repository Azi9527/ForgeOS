const token = document.querySelector('meta[name="forge-token"]').content;
const state = { selectedTask: null, tasks: [], jobs: [], doctor: null, polling: null, pendingDecision: null };

const element = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
})[char]);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-ForgeOS-Token": token, ...(options.body ? { "Content-Type": "application/json" } : {}) }
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error?.message || `HTTP ${response.status}`);
  return body;
}

function toast(message, error = false) {
  const node = element("toast");
  node.textContent = message;
  node.classList.toggle("error", error);
  node.classList.remove("hidden");
  window.setTimeout(() => node.classList.add("hidden"), 4000);
}

async function refresh() {
  try {
    const status = await api("/api/status");
    if (!state.doctor) state.doctor = await api("/api/doctor");
    element("connection-dot").classList.add("online");
    element("workspace").textContent = status.workspace;
    if (!status.initialized) {
      element("project-name").textContent = "未初始化";
      element("init-panel").classList.remove("hidden");
      element("pilot-panel").classList.add("hidden");
      element("workspace-panel").classList.add("hidden");
      ForgePilot.renderBootstrap(state.doctor);
      return;
    }
    element("project-name").textContent = status.project.name;
    element("init-panel").classList.add("hidden");
    element("workspace-panel").classList.remove("hidden");
    renderSummary(status);
    renderOperations(status.operations || {});
    renderOperator(status.operator || {});
    const [{ tasks }, { jobs }, { events }] = await Promise.all([
      api("/api/tasks"), api("/api/jobs"), api("/api/audit")
    ]);
    state.tasks = tasks;
    state.jobs = jobs;
    ForgePilot.renderWorkspace(status, state.doctor, tasks);
    renderTasks();
    renderJobs(jobs);
    renderAudit(events);
    if (state.selectedTask && tasks.some((task) => task.id === state.selectedTask)) {
      await selectTask(state.selectedTask, false);
    }
  } catch (error) {
    element("connection-dot").classList.remove("online");
    toast(error.message, true);
  }
}

function renderSummary(status) {
  const entries = Object.entries(status.tasks_by_status || {});
  element("status-summary").innerHTML = entries.length
    ? entries.map(([name, count]) => `<span class="count-pill">${escapeHtml(name)} ${count}</span>`).join("")
    : '<span class="count-pill">暂无任务</span>';
}

function renderOperations(operations) {
  const migration = operations.migration || null;
  const integrity = operations.integrity || null;
  const recovery = operations.recovery || null;
  element("operations-status").textContent = JSON.stringify({ migration, integrity, recovery }, null, 2);
  element("migration-button").disabled = !migration?.required;
}

function renderTasks() {
  element("task-list").innerHTML = state.tasks.map((task) => `
    <button class="task-card ${task.id === state.selectedTask ? "selected" : ""}" data-task="${escapeHtml(task.id)}">
      <span class="status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span>
      <strong>${escapeHtml(task.title)}</strong>
      <small>${escapeHtml(task.id)} · ${escapeHtml(task.task_type)}</small>
    </button>`).join("");
  document.querySelectorAll("[data-task]").forEach((node) => {
    node.addEventListener("click", () => selectTask(node.dataset.task));
  });
}

async function selectTask(taskId, rerenderList = true) {
  state.selectedTask = taskId;
  if (rerenderList) renderTasks();
  const detail = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
  renderDetail(detail);
}

function actionButtons(task, activeJob = null) {
  if (activeJob) {
    const label = activeJob.kind === "run" ? "Codex 运行中…" : "Validation 运行中…";
    const interrupt = activeJob.kind === "run"
      ? '<button class="danger" data-action="interrupt">中断 Codex</button>'
      : "";
    return `<button class="primary" disabled aria-busy="true">${label}</button>${interrupt}<button class="danger" data-action="cancel">取消任务</button>`;
  }
  const buttons = [];
  if (["CREATED", "IMPLEMENTING", "REPAIRING"].includes(task.status)) {
    buttons.push('<button class="primary" data-action="run">运行 Codex</button>');
  }
  if (task.status === "BLOCKED" && ["IMPLEMENTING", "REPAIRING"].includes(task.blocked_from)) {
    buttons.push('<button class="primary" data-action="run">重试 Codex</button>');
  }
  if (task.status === "VALIDATING") buttons.push('<button class="primary" data-action="validate">执行验证</button>');
  if (task.status === "BLOCKED" && task.blocked_from === "VALIDATING") {
    buttons.push('<button class="primary" data-action="validate">重试验证</button>');
  }
  if (task.status === "REVIEWING") {
    if (task.validation?.regression_report_id) {
      buttons.push('<button class="primary" data-action="review-approve">审核通过</button>');
      buttons.push('<button class="danger" data-action="review-reject">退回修复</button>');
    } else {
      buttons.push('<button class="secondary" disabled title="先退回并重新执行以生成 N2 baseline">缺少 L4 Regression</button>');
      buttons.push('<button class="danger" data-action="review-reject">退回并迁移到 N2</button>');
    }
  }
  if (task.status === "ACCEPTING") buttons.push('<button class="primary" data-action="accept">最终验收</button>');
  if (!["DONE", "FAILED", "CANCELLED"].includes(task.status)) {
    buttons.push('<button class="danger" data-action="cancel">取消任务</button>');
  }
  return buttons.join("");
}

function renderDetail(detail) {
  const task = detail.task;
  const activeJob = detail.jobs.find((job) => ["QUEUED", "RUNNING"].includes(job.state));
  element("empty-state").classList.add("hidden");
  const node = element("task-detail");
  node.classList.remove("hidden");
  const criteria = task.acceptance_criteria.map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const lastExecution = detail.executions.at(-1);
  const lastValidation = detail.validations.at(-1);
  const lastRegression = detail.regressions.at(-1);
  const lastReport = detail.reports.at(-1);
  const lastAttempt = detail.attempts.at(-1);
  const baseline = detail.git.filter((snapshot) => snapshot.kind === "baseline").at(-1);
  const current = detail.git.filter((snapshot) => snapshot.kind === "current").at(-1);
  const lastContext = detail.contexts.at(-1);
  const lastMemorySelection = (detail.memory_selections || []).at(-1);
  const relatedMemories = detail.memories || [];
  const lastPolicy = (detail.policy_evaluations || []).at(-1);
  const lastBudget = (detail.budgets || []).at(-1);
  const progress = activeJob?.progress || null;
  const guidance = ForgePilot.taskGuidance(task, activeJob, Boolean(lastReport));
  node.innerHTML = `
    <div class="task-heading">
      <div><span class="status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span><h2>${escapeHtml(task.title)}</h2><p>${escapeHtml(task.id)} · revision ${task.revision}</p></div>
      <div class="actions">${actionButtons(task, activeJob)}${lastReport ? '<button class="secondary" id="download-task-report">下载报告</button>' : ""}</div>
    </div>
    <div class="detail-grid">
      <article class="detail-block wide next-step ${escapeHtml(guidance.tone)}"><h3>推荐下一步</h3><strong>${escapeHtml(guidance.title)}</strong><p>${escapeHtml(guidance.detail)}</p></article>
      <article class="detail-block wide"><h3>目标</h3><p>${escapeHtml(task.objective)}</p></article>
      <article class="detail-block"><h3>验收条件</h3><ul>${criteria}</ul></article>
      <article class="detail-block"><h3>运行关联</h3><p>Thread: <code>${escapeHtml(task.codex_thread_id || "未启动")}</code></p><p>Turn: <code>${escapeHtml(task.last_turn_id || "—")}</code></p></article>
      ${activeJob?.kind === "run" ? `<article class="detail-block wide"><h3>实时运行</h3><div class="evidence">${escapeHtml(JSON.stringify(progress || { phase: "queued" }, null, 2))}</div><form id="steer-form" class="steer-form"><input name="input" required maxlength="10000" placeholder="向当前 Turn 补充约束"><button class="secondary" type="submit">发送 Steer</button></form></article>` : ""}
      <article class="detail-block wide"><h3>Execution Attempt</h3><div class="evidence">${escapeHtml(lastAttempt ? JSON.stringify(lastAttempt, null, 2) : "尚无持久执行记录")}</div></article>
      <article class="detail-block wide"><h3>Git Evidence</h3><div class="evidence">${escapeHtml(JSON.stringify({ baseline: baseline || null, current: current || null }, null, 2))}</div></article>
      <article class="detail-block wide"><h3>Context Package</h3><div class="evidence">${escapeHtml(lastContext ? JSON.stringify(lastContext, null, 2) : "尚无 Context Package")}</div></article>
      <article class="detail-block wide"><h3>N3 Engineering Memory</h3><div class="evidence">${escapeHtml(JSON.stringify({ selection: lastMemorySelection || null, records: relatedMemories }, null, 2))}</div></article>
      <article class="detail-block wide"><h3>N3 ForgePolicy</h3><div class="evidence">${escapeHtml(lastPolicy ? JSON.stringify(lastPolicy, null, 2) : "执行前尚未产生 Policy Evaluation")}</div></article>
      <article class="detail-block wide"><h3>N4 Execution Budget</h3><div class="evidence">${escapeHtml(lastBudget ? JSON.stringify(lastBudget, null, 2) : "尚未评估执行预算")}</div></article>
      <article class="detail-block wide"><h3>N4 Recovery & Cancellation</h3><div class="evidence">${escapeHtml(JSON.stringify({ cancellation: detail.cancellation || null, recovery: detail.recovery_runs || [] }, null, 2))}</div></article>
      <article class="detail-block wide"><h3>N4 Evidence Integrity</h3><div class="evidence">${escapeHtml(detail.integrity ? JSON.stringify(detail.integrity, null, 2) : "尚未执行持久化完整性扫描")}</div></article>
      <article class="detail-block wide"><h3>最新 Codex 响应</h3><div class="evidence">${escapeHtml(lastExecution?.final_response || "尚无执行证据")}</div></article>
      <article class="detail-block wide"><h3>Typed Validation</h3><div class="evidence">${escapeHtml(JSON.stringify({ baseline: detail.validation_baseline || null, current: lastValidation || null }, null, 2))}</div></article>
      <article class="detail-block wide"><h3>L4 Regression</h3><div class="evidence">${escapeHtml(lastRegression ? JSON.stringify(lastRegression, null, 2) : "尚无回归报告")}</div></article>
      <article class="detail-block wide"><h3>Forge Task Report</h3><div class="evidence">${escapeHtml(lastReport ? JSON.stringify(lastReport, null, 2) : "任务完成验收后生成")}</div></article>
    </div>`;
  node.querySelectorAll("[data-action]").forEach((button) => {
    button.addEventListener("click", () => performAction(button, task));
  });
  const steerForm = element("steer-form");
  if (steerForm) steerForm.addEventListener("submit", (event) => submitSteer(event, task));
  const reportButton = element("download-task-report");
  if (reportButton) reportButton.addEventListener("click", () => downloadJson(
    `/api/tasks/${encodeURIComponent(task.id)}/report/export`, `${task.id}-task-report.json`
  ));
}

async function downloadJson(path, filename) {
  try {
    ForgePilot.saveJson(await api(path), filename);
    toast(`已下载 ${filename}`);
  } catch (error) { toast(error.message, true); }
}

async function performAction(button, task) {
  const action = button.dataset.action;
  if (action.startsWith("review") || action === "accept" || action === "cancel") {
    openDecision(action, task);
    return;
  }
  const originalLabel = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  if (action === "run") button.textContent = "正在提交…";
  if (action === "validate") button.textContent = "正在提交验证…";
  if (action === "review-approve") button.textContent = "正在审核…";
  if (action === "review-reject") button.textContent = "正在退回…";
  if (action === "accept") button.textContent = "正在验收…";
  try {
    if (action === "run") {
      await api(`/api/tasks/${task.id}/run`, { method: "POST", body: "{}" });
      toast("Codex 作业已进入队列");
    } else if (action === "validate") {
      await api(`/api/tasks/${task.id}/validate`, { method: "POST", body: "{}" });
      toast("Validation 作业已进入队列");
    } else if (action === "interrupt") {
      await api(`/api/tasks/${task.id}/interrupt`, { method: "POST", body: "{}" });
      toast("已请求中断当前 Codex Turn");
    }
    await refresh();
  } catch (error) {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = originalLabel;
    toast(error.message, true);
  }
}

function openDecision(action, task) {
  state.pendingDecision = { action, taskId: task.id, criteria: task.acceptance_criteria };
  const approved = action === "review-approve";
  element("decision-title").textContent = action === "cancel" ? "取消任务" : action === "accept"
    ? "最终验收" : approved ? "审核通过" : "退回修复";
  element("decision-actor-label").textContent = action === "cancel" ? "操作人" : action === "accept" ? "验收人" : "审核人";
  element("decision-submit").textContent = action === "cancel" ? "确认取消" : action === "accept"
    ? "确认验收" : approved ? "确认通过" : "确认退回";
  element("decision-fields").innerHTML = action === "cancel" ? '<p>取消将持久化请求；运行中的 Codex Turn 会先收到 interrupt，随后 Task 进入 CANCELLED。</p>' : action === "accept"
    ? acceptanceFields(task.acceptance_criteria) : reviewFields(approved);
  element("decision-dialog").showModal();
}

const reviewDimensions = [
  ["ARCHITECTURE", "Architecture"],
  ["CODE_QUALITY", "Code Quality"],
  ["RISK", "Risk"],
  ["TESTS", "Tests"],
  ["BACKWARD_COMPATIBILITY", "Backward Compatibility"],
  ["TECHNICAL_DEBT", "Technical Debt"]
];

function reviewFields(approved) {
  const defaultStatus = approved ? "PASS" : "CONCERN";
  const rows = reviewDimensions.map(([dimension, label]) => `
    <div class="decision-row">
      <strong>${escapeHtml(label)}</strong>
      <select name="review_status_${dimension}">
        <option ${defaultStatus === "PASS" ? "selected" : ""}>PASS</option>
        <option ${defaultStatus === "CONCERN" ? "selected" : ""}>CONCERN</option>
        <option>NOT_APPLICABLE</option>
      </select>
      <input name="review_note_${dimension}" value="已检查" required maxlength="2000" aria-label="${escapeHtml(label)} evidence">
    </div>`).join("");
  return `<fieldset><legend>Review Checklist</legend>${rows}</fieldset>
    <label>风险（每行一条）<textarea name="risks" rows="2" maxlength="4000"></textarea></label>
    <label>技术债（每行一条）<textarea name="technical_debt" rows="2" maxlength="4000"></textarea></label>`;
}

function acceptanceFields(criteria) {
  const rows = criteria.map((criterion, index) => {
    const id = `AC-${String(index + 1).padStart(3, "0")}`;
    return `<div class="criterion-row">
      <strong>${escapeHtml(id)}</strong><span>${escapeHtml(criterion)}</span>
      <select name="criterion_status_${index}"><option>PASS</option><option>FAIL</option><option>SKIP</option></select>
      <input name="criterion_evidence_${index}" required maxlength="4000" placeholder="可核验的证据" aria-label="${escapeHtml(id)} evidence">
    </div>`;
  }).join("");
  return `<fieldset><legend>L5 Acceptance Criteria</legend>${rows}</fieldset>`;
}

element("decision-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    element("decision-dialog").close();
    state.pendingDecision = null;
    return;
  }
  const pending = state.pendingDecision;
  if (!pending) return;
  const form = event.currentTarget;
  const data = new FormData(form);
  const actor = data.get("actor").trim();
  const summary = data.get("summary").trim();
  try {
    if (pending.action === "cancel") {
      if (!summary) throw new Error("取消任务必须填写说明");
      await api(`/api/tasks/${pending.taskId}/cancel`, {
        method: "POST", body: JSON.stringify({ requested_by: actor, reason: summary })
      });
      toast("取消请求已记录");
    } else if (pending.action === "accept") {
      const criteria = pending.criteria.map((criterion, index) => ({
        criterion_id: `AC-${String(index + 1).padStart(3, "0")}`,
        criterion,
        status: data.get(`criterion_status_${index}`),
        evidence: data.get(`criterion_evidence_${index}`).trim()
      }));
      await api(`/api/tasks/${pending.taskId}/accept`, {
        method: "POST", body: JSON.stringify({ accepted_by: actor, note: summary, criteria })
      });
      toast("任务已完成验收");
    } else {
      const approved = pending.action === "review-approve";
      const checklist = reviewDimensions.map(([dimension]) => ({
        dimension,
        status: data.get(`review_status_${dimension}`),
        note: data.get(`review_note_${dimension}`).trim()
      }));
      await api(`/api/tasks/${pending.taskId}/review`, {
        method: "POST", body: JSON.stringify({
          approved, reviewer: actor, summary, checklist,
          risks: data.get("risks").split("\n").map((item) => item.trim()).filter(Boolean),
          technical_debt: data.get("technical_debt").split("\n").map((item) => item.trim()).filter(Boolean)
        })
      });
      toast(approved ? "审核已通过" : "任务已退回修复");
    }
    element("decision-dialog").close();
    state.pendingDecision = null;
    await refresh();
  } catch (error) { toast(error.message, true); }
});

async function submitSteer(event, task) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  try {
    await api(`/api/tasks/${task.id}/steer`, {
      method: "POST", body: JSON.stringify({ input: data.get("input") })
    });
    form.reset();
    toast("Steer 已发送");
  } catch (error) { toast(error.message, true); }
}

function renderJobs(jobs) {
  element("job-list").innerHTML = jobs.slice(0, 8).map((job) => `
    <div class="activity-item ${job.state.toLowerCase()}"><strong>${escapeHtml(job.kind)} · ${escapeHtml(job.task_id)}</strong><small>${escapeHtml(job.state)}${job.progress?.event?.summary?.phase ? ` · ${escapeHtml(job.progress.event.summary.phase)}` : ""}${job.error_message ? ` · ${escapeHtml(job.error_message)}` : ""}</small></div>`
  ).join("") || '<div class="activity-item"><small>暂无运行作业</small></div>';
}

function renderAudit(events) {
  element("audit-list").innerHTML = events.slice(-20).reverse().map((event) => `
    <div class="activity-item"><strong>${escapeHtml(event.event_type)}</strong><small>${escapeHtml(event.task_id || "project")} · ${escapeHtml(event.occurred_at)}</small></div>`
  ).join("");
}

element("init-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  try {
    const argv = JSON.parse(data.get("check_argv"));
    await api("/api/project/init", { method: "POST", body: JSON.stringify({
      name: data.get("name"), validation_checks: [{
        name: data.get("check_name"), level: data.get("check_level"), argv
      }]
    }) });
    toast("ForgeOS 项目已初始化");
    state.doctor = null;
    await refresh();
  } catch (error) { toast(error.message, true); }
});

element("new-task-button").addEventListener("click", () => element("task-dialog").showModal());
element("pilot-new-task").addEventListener("click", () => element("task-dialog").showModal());
element("diagnostics-download").addEventListener("click", () => downloadJson(
  "/api/diagnostics/export", "forgeos-diagnostics.json"
));
element("readiness-refresh").addEventListener("click", async () => {
  state.doctor = null;
  await refresh();
  toast("运行条件已重新检查");
});
element("integrity-scan-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const report = await api("/api/operations/integrity-scan", { method: "POST", body: "{}" });
    toast(report.passed ? "Evidence Integrity PASS" : "Evidence Integrity 检测到错误", !report.passed);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
element("migration-button").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await api("/api/migration/apply", { method: "POST", body: "{}" });
    toast("协议迁移已应用");
    await refresh();
  } catch (error) { toast(error.message, true); }
});
element("task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (event.submitter?.value === "cancel") { element("task-dialog").close(); return; }
  const form = event.currentTarget;
  const data = new FormData(form);
  try {
    const task = await api("/api/tasks", { method: "POST", body: JSON.stringify({
      title: data.get("title"), task_type: data.get("task_type"), risk: data.get("risk"),
      objective: data.get("objective"), acceptance_criteria: data.get("acceptance").split("\n").filter(Boolean)
    }) });
    element("task-dialog").close();
    form.reset();
    state.selectedTask = task.id;
    toast(`已创建 ${task.id}`);
    await refresh();
  } catch (error) { toast(error.message, true); }
});

setupOperator();
state.polling = window.setInterval(refresh, 1800);
refresh();
