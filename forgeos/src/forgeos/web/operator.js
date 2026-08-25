function renderOperator(operator) {
  const release = operator.release || null;
  const fixture = operator.fixtures || null;
  element("release-status").textContent = JSON.stringify({
    package_version: operator.package_version || "—",
    latest_release: release ? { id: release.id, passed: release.passed, checked_at: release.checked_at } : null,
    protocol_fixtures: fixture ? { passed: fixture.passed, count: fixture.fixtures?.length || 0 } : null,
    memory_count: operator.memory_count || 0,
    policy_count: operator.policy_count || 0
  }, null, 2);
}

function setupOperator() {
  element("release-check-button").addEventListener("click", runReleaseCheck);
  element("operator-button").addEventListener("click", openOperator);
  element("operator-close").addEventListener("click", () => element("operator-dialog").close());
  document.querySelectorAll("[data-operator-tab]").forEach((button) => {
    button.addEventListener("click", () => selectOperatorTab(button.dataset.operatorTab));
  });
  element("memory-create-form").addEventListener("submit", createMemoryFromOperator);
  element("policy-create-form").addEventListener("submit", createPolicyFromOperator);
  element("audit-query-form").addEventListener("submit", queryAuditFromOperator);
}

async function runReleaseCheck(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const report = await api("/api/release/check", { method: "POST", body: "{}" });
    toast(report.passed ? "N5 Release Readiness PASS" : "发布检查发现阻塞项", !report.passed);
    await refresh();
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}

async function openOperator() {
  element("operator-dialog").showModal();
  await refreshOperatorData();
}

function selectOperatorTab(tab) {
  document.querySelectorAll("[data-operator-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.operatorTab === tab);
  });
  for (const name of ["memory", "policy", "audit"]) {
    element(`operator-${name}`).classList.toggle("hidden", name !== tab);
  }
}

async function refreshOperatorData() {
  try {
    const [{ memories }, { policies }, audit] = await Promise.all([
      api("/api/memories"), api("/api/policies"), api("/api/audit?limit=100")
    ]);
    renderMemoryManager(memories);
    renderPolicyManager(policies);
    renderOperatorAudit(audit);
  } catch (error) { toast(error.message, true); }
}

function renderMemoryManager(memories) {
  element("memory-list").innerHTML = memories.map((memory) => `
    <article class="operator-card">
      <header><h3>${escapeHtml(memory.title)}</h3><span class="status ${escapeHtml(memory.status)}">${escapeHtml(memory.status)}</span></header>
      <p>${escapeHtml(memory.body)}</p>
      <small>${escapeHtml(memory.kind)} · revision ${memory.revision} · ${escapeHtml(memory.id)}</small>
      ${memory.status === "DRAFT" ? `<div class="actions"><button class="primary" data-memory-action="accept" data-memory-id="${escapeHtml(memory.id)}" data-revision="${memory.revision}">接受</button><button class="danger" data-memory-action="reject" data-memory-id="${escapeHtml(memory.id)}" data-revision="${memory.revision}">拒绝</button></div>` : ""}
    </article>`).join("") || '<div class="operator-card"><small>暂无 Memory</small></div>';
  document.querySelectorAll("[data-memory-action]").forEach((button) => {
    button.addEventListener("click", () => decideMemoryFromOperator(button));
  });
}

async function createMemoryFromOperator(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  try {
    await api("/api/memories", { method: "POST", body: JSON.stringify({
      kind: data.get("kind"), title: data.get("title"), body: data.get("body"),
      created_by: data.get("created_by"),
      tags: data.get("tags").split(",").map((item) => item.trim()).filter(Boolean)
    }) });
    form.reset();
    toast("Draft Memory 已创建");
    await refreshOperatorData();
  } catch (error) { toast(error.message, true); }
}

async function decideMemoryFromOperator(button) {
  const actor = element("memory-actor").value.trim();
  const reason = element("memory-reason").value.trim();
  if (!actor || !reason) { toast("Memory 决策需要操作人与说明", true); return; }
  try {
    await api(`/api/memories/${encodeURIComponent(button.dataset.memoryId)}/${button.dataset.memoryAction}`, {
      method: "POST", body: JSON.stringify({
        decided_by: actor, reason, expected_revision: Number(button.dataset.revision)
      })
    });
    toast(button.dataset.memoryAction === "accept" ? "Memory 已接受" : "Memory 已拒绝");
    await refreshOperatorData();
  } catch (error) { toast(error.message, true); }
}

function renderPolicyManager(policies) {
  element("policy-list").innerHTML = policies.map((policy) => `
    <article class="operator-card">
      <header><h3>${escapeHtml(policy.name)}</h3><span class="status">${policy.built_in ? "BUILT-IN" : policy.active ? "ACTIVE" : "RETIRED"}</span></header>
      <p>${escapeHtml(policy.reason)}</p>
      <small>${escapeHtml(policy.id)} · ${escapeHtml(policy.target)} · ${escapeHtml(policy.patterns.join(", "))}</small>
      ${!policy.built_in && policy.active ? `<div class="actions"><button class="danger" data-policy-retire="${escapeHtml(policy.id)}">退役规则</button></div>` : ""}
    </article>`).join("");
  document.querySelectorAll("[data-policy-retire]").forEach((button) => {
    button.addEventListener("click", () => retirePolicyFromOperator(button));
  });
}

async function createPolicyFromOperator(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const data = new FormData(form);
  try {
    await api("/api/policies", { method: "POST", body: JSON.stringify({
      id: data.get("id"), name: data.get("name"), target: data.get("target"),
      patterns: data.get("patterns").split("\n").map((item) => item.trim()).filter(Boolean),
      reason: data.get("reason"), created_by: data.get("created_by")
    }) });
    form.reset();
    toast("Additive DENY Policy 已创建");
    await refreshOperatorData();
  } catch (error) { toast(error.message, true); }
}

async function retirePolicyFromOperator(button) {
  const actor = element("policy-actor").value.trim();
  const reason = element("policy-reason").value.trim();
  if (!actor || !reason) { toast("Policy 退役需要操作人与说明", true); return; }
  try {
    await api(`/api/policies/${encodeURIComponent(button.dataset.policyRetire)}/retire`, {
      method: "POST", body: JSON.stringify({ retired_by: actor, reason })
    });
    toast("Policy 已退役并保留证据");
    await refreshOperatorData();
  } catch (error) { toast(error.message, true); }
}

async function queryAuditFromOperator(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const query = new URLSearchParams({ limit: "100" });
  for (const name of ["task_id", "event_type", "actor"]) {
    const value = data.get(name).trim();
    if (value) query.set(name, value);
  }
  try { renderOperatorAudit(await api(`/api/audit?${query}`)); }
  catch (error) { toast(error.message, true); }
}

function renderOperatorAudit(page) {
  element("operator-audit-list").innerHTML = page.events.map((event) => `
    <article class="operator-card">
      <header><h3>${escapeHtml(event.event_type)}</h3><span>#${event.sequence}</span></header>
      <small>${escapeHtml(event.actor)} · ${escapeHtml(event.task_id || "project")} · ${escapeHtml(event.occurred_at)}</small>
      <div class="evidence">${escapeHtml(JSON.stringify(event.payload, null, 2))}</div>
    </article>`).join("") || '<div class="operator-card"><small>无匹配审计事件</small></div>';
}
