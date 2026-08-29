<script lang="ts">
  import {
    AlertCircle,
    CheckCircle2,
    ChevronDown,
    ChevronUp,
    CircleDashed,
    Clock3,
    History,
    Play,
    Save,
    Settings2,
    Square,
    TerminalSquare,
    XCircle
  } from "lucide-svelte";

  import { api } from "$lib/api";
  import { findProjectValidationCleanupQuarantine } from "$lib/project-validation-state";
  import type {
    ProjectValidationCheck as ValidationCheck,
    ProjectValidationRun as ValidationRun,
    SessionFolder
  } from "$lib/types";

  let { project, readOnly }: { project: SessionFolder; readOnly: boolean } = $props();

  let checks = $state<ValidationCheck[]>(defaultChecks());
  let runs = $state<ValidationRun[]>([]);
  let configurationOpen = $state(false);
  let expandedRunId = $state<string | null>(null);
  let running = $state(false);
  let cancelling = $state(false);
  let acknowledgingCleanup = $state(false);
  let error = $state("");
  let persistenceMode = $state<"gateway" | "error" | "loading">("loading");
  let lifecycleRevision = $state<number | null>(null);
  let persistedChecks = $state<ValidationCheck[]>([]);
  let loadGeneration = 0;

  const configuredChecks = $derived(checks.filter((check) => check.command.trim()));
  const latestRun = $derived(runs[0] ?? null);
  const gatewayRunning = $derived(latestRun?.status === "running");
  const passedCount = $derived(latestRun?.checks.filter((check) => check.status === "passed").length ?? 0);
  const cleanupQuarantine = $derived(findProjectValidationCleanupQuarantine(runs));

  function projectId() {
    if (!project.projectId) throw new Error("项目尚未完成 Project Registry V2 注册，请先在项目中心导入或重建项目。");
    return project.projectId;
  }

  function defaultChecks(): ValidationCheck[] {
    return [
      { id: "build", label: "项目构建", command: "", required: true },
      { id: "test", label: "自动测试", command: "", required: true },
      { id: "lint", label: "静态检查", command: "", required: true }
    ];
  }

  function applyLifecycle(lifecycle: Awaited<ReturnType<typeof api.getProjectLifecycle>>) {
    lifecycleRevision = lifecycle.revision;
    checks = lifecycle.validation.checks.length > 0 ? lifecycle.validation.checks : defaultChecks();
    persistedChecks = lifecycle.validation.checks;
    runs = lifecycle.validation.runs;
    persistenceMode = "gateway";
  }

  function showGatewayFailure(message: string) {
    checks = defaultChecks();
    persistedChecks = [];
    runs = [];
    lifecycleRevision = null;
    persistenceMode = "error";
    configurationOpen = false;
    expandedRunId = null;
    error = `${message}。未展示任何本机缓存。`;
  }

  function describeFailure(cause: unknown) {
    return cause instanceof Error ? cause.message : String(cause);
  }

  function isRevisionConflict(message: string) {
    return /\b(?:changed|conflict|revision)\b|\b409\b|已变更|冲突/iu.test(message);
  }

  async function handleMutationFailure(prefix: string, cause: unknown, targetProjectId: string) {
    if (project.projectId !== targetProjectId) return;
    const message = describeFailure(cause);
    error = `${prefix}：${message}`;
    if (!isRevisionConflict(message)) return;

    const generation = ++loadGeneration;
    try {
      const lifecycle = await api.getProjectLifecycle(targetProjectId);
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      applyLifecycle(lifecycle);
      error = `${prefix}：${message}。已自动重新加载项目网关中的最新状态，请重试。`;
    } catch (reloadCause) {
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      error = `${prefix}：${message}。重新加载权威状态失败：${describeFailure(reloadCause)}。当前画面已保留，请稍后重试。`;
    }
  }

  async function saveConfiguration() {
    if (readOnly || persistenceMode !== "gateway" || lifecycleRevision === null) return;
    const targetProjectId = projectId();
    const proposedChecks = checks.map((check) => ({ ...check, command: check.command.trim() }));
    error = "";
    try {
      const lifecycle = await api.saveProjectValidation(targetProjectId, proposedChecks, lifecycleRevision);
      if (project.projectId !== targetProjectId) return;
      applyLifecycle(lifecycle);
      configurationOpen = false;
    } catch (cause) {
      await handleMutationFailure("验证配置未保存", cause, targetProjectId);
    }
  }

  function updateCommand(id: string, command: string) {
    checks = checks.map((check) => check.id === id ? { ...check, command } : check);
  }

  function updateRequired(id: string, required: boolean) {
    checks = checks.map((check) => check.id === id ? { ...check, required } : check);
  }

  function formatTime(value: number | null) {
    if (!value) return "—";
    return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(value);
  }

  function formatDuration(value: number | null) {
    if (value === null) return "—";
    if (value < 1000) return `${value} ms`;
    return `${(value / 1000).toFixed(1)} 秒`;
  }

  async function runValidation() {
    if (running || gatewayRunning || readOnly || persistenceMode !== "gateway" || lifecycleRevision === null || cleanupQuarantine) return;
    if (!project.rootPath) {
      error = "请先在项目设置中绑定根目录。";
      return;
    }
    if (configuredChecks.length === 0) {
      configurationOpen = true;
      error = "请至少配置一条验证命令。";
      return;
    }

    running = true;
    cancelling = false;
    error = "";
    const targetProjectId = projectId();
    const expectedRevision = lifecycleRevision;
    try {
      const lifecycle = await api.runProjectValidation(targetProjectId, expectedRevision);
      if (project.projectId !== targetProjectId) return;
      applyLifecycle(lifecycle);
      expandedRunId = lifecycle.validation.runs[0]?.id ?? null;
    } catch (cause) {
      await handleMutationFailure("网关验证未完成", cause, targetProjectId);
    } finally {
      running = false;
      cancelling = false;
    }
  }

  async function cancelValidation() {
    if (!running && !gatewayRunning) return;
    cancelling = true;
    error = "";
    const targetProjectId = projectId();
    try {
      await api.cancelProjectValidation(targetProjectId);
      let terminal = false;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
        const lifecycle = await api.getProjectLifecycle(targetProjectId);
        if (project.projectId !== targetProjectId) return;
        applyLifecycle(lifecycle);
        if (lifecycle.validation.runs[0]?.status !== "running") {
          terminal = true;
          break;
        }
      }
      if (!terminal) {
        error = "验证仍在后台执行清理，请稍后刷新项目验证状态；在清理完成前不要启动新的验证。";
      }
    } catch (cause) {
      await handleMutationFailure("验证停止请求失败", cause, targetProjectId);
    } finally {
      cancelling = false;
    }
  }

  async function acknowledgeValidationCleanup() {
    if (readOnly || acknowledgingCleanup || persistenceMode !== "gateway" || lifecycleRevision === null || !cleanupQuarantine) return;
    const confirmed = window.confirm(
      "只有在你已通过任务管理器或运维工具确认上一条验证命令及其所有子进程均已停止后，才可解除隔离。解除操作会写入项目审计记录。是否继续？"
    );
    if (!confirmed) return;

    acknowledgingCleanup = true;
    error = "";
    const targetProjectId = projectId();
    const expectedRevision = lifecycleRevision;
    const runId = cleanupQuarantine.id;
    try {
      const lifecycle = await api.acknowledgeProjectValidationCleanup(targetProjectId, runId, expectedRevision);
      if (project.projectId !== targetProjectId) return;
      applyLifecycle(lifecycle);
    } catch (cause) {
      await handleMutationFailure("验证进程隔离未解除", cause, targetProjectId);
    } finally {
      acknowledgingCleanup = false;
    }
  }

  async function restoreLifecycle(targetProjectId: string, generation: number) {
    try {
      const lifecycle = await api.getProjectLifecycle(targetProjectId);
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      applyLifecycle(lifecycle);
    } catch (cause) {
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      showGatewayFailure(`无法从项目网关读取验证证据：${cause instanceof Error ? cause.message : String(cause)}`);
    }
  }

  $effect(() => {
    const targetProjectId = project.projectId;
    const generation = ++loadGeneration;
    checks = defaultChecks();
    persistedChecks = [];
    runs = [];
    lifecycleRevision = null;
    persistenceMode = "loading";
    configurationOpen = false;
    expandedRunId = null;
    running = false;
    cancelling = false;
    acknowledgingCleanup = false;
    error = "";
    if (!targetProjectId) {
      persistenceMode = "error";
      error = "项目尚未完成 Project Registry V2 注册，无法读取权威验证证据。";
      return;
    }
    void restoreLifecycle(targetProjectId, generation);
  });
</script>

<section class="h-full overflow-y-auto bg-[#f7f8fb]" data-testid="project-validation-workspace">
  <div class="mx-auto w-full max-w-6xl px-6 py-8 lg:px-10 lg:py-10">
    <header class="flex flex-col gap-5 border-b border-slate-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.22em] text-violet-600">ENGINEERING EVIDENCE</p>
        <h1 class="mt-2 text-2xl font-bold text-slate-950">验证与工程证据</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">在项目根目录中受控执行构建、测试和静态检查。证据绑定 Git 版本与操作者，并在项目网关中有界留存。</p>
        <p class="mt-2 text-[11px] font-semibold text-slate-400">{persistenceMode === "gateway" ? "项目网关权威执行与持久化" : persistenceMode === "error" ? "项目网关不可用 · 未展示本机缓存" : "正在读取项目网关证据"}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 disabled:opacity-50" disabled={readOnly || running || gatewayRunning || persistenceMode !== "gateway"} onclick={() => (configurationOpen = !configurationOpen)} type="button"><Settings2 size={16} />配置流程</button>
        {#if running || gatewayRunning}
          <button class="inline-flex h-10 items-center gap-2 rounded-xl bg-red-600 px-4 text-sm font-bold text-white disabled:opacity-50" disabled={cancelling} onclick={cancelValidation} type="button"><Square size={14} />{cancelling ? "正在停止" : "停止验证"}</button>
        {:else}
          <button class="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-bold text-white disabled:opacity-50" data-testid="validation-run" disabled={readOnly || gatewayRunning || persistenceMode !== "gateway" || lifecycleRevision === null || configuredChecks.length === 0 || cleanupQuarantine !== null} onclick={runValidation} type="button"><Play size={15} />运行验证</button>
        {/if}
      </div>
    </header>

    {#if error}<div class="mt-5 flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={16} />{error}</div>{/if}

    {#if cleanupQuarantine}
      <section class="mt-5 flex flex-col gap-3 rounded-2xl border border-amber-300 bg-amber-50 px-4 py-4 text-sm text-amber-950 sm:flex-row sm:items-center sm:justify-between" data-testid="validation-cleanup-quarantine">
        <div class="flex min-w-0 items-start gap-3"><AlertCircle class="mt-0.5 shrink-0 text-amber-600" size={17} /><div><p class="font-bold">项目验证已进入进程隔离</p><p class="mt-1 text-xs leading-5 text-amber-800">网关未能在硬截止前确认运行 {cleanupQuarantine.id} 的完整进程树已停止。为防止残留进程污染新证据，网关重启后仍会阻止再次验证。</p></div></div>
        <button class="shrink-0 rounded-xl border border-amber-400 bg-white px-4 py-2 text-xs font-bold text-amber-900 disabled:opacity-50" disabled={readOnly || acknowledgingCleanup || lifecycleRevision === null} onclick={acknowledgeValidationCleanup} type="button">{acknowledgingCleanup ? "正在解除" : "确认已清理并解除隔离"}</button>
      </section>
    {/if}

    {#if configurationOpen}
      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="validation-configuration">
        <div class="flex items-center justify-between gap-3"><div><h2 class="text-sm font-bold text-slate-900">项目验证流程</h2><p class="mt-1 text-xs text-slate-500">命令保存到项目网关并由网关按顺序执行；必需检查失败后停止后续步骤。</p></div><button class="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white disabled:opacity-50" disabled={readOnly || persistenceMode !== "gateway" || lifecycleRevision === null} onclick={saveConfiguration} type="button"><Save size={14} />保存配置</button></div>
        <div class="mt-4 space-y-3">
          {#each checks as check (check.id)}
            <div class="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[8rem_minmax(0,1fr)_7rem] md:items-center">
              <label class="text-xs font-bold text-slate-700" for={`validation-${check.id}`}>{check.label}</label>
              <input class="rounded-xl border border-slate-200 bg-white px-3 py-2.5 font-mono text-xs text-slate-800 outline-none focus:border-violet-400" id={`validation-${check.id}`} oninput={(event) => updateCommand(check.id, event.currentTarget.value)} placeholder="例如：npm run build" value={check.command} />
              <label class="flex items-center gap-2 text-xs font-semibold text-slate-600"><input checked={check.required} onchange={(event) => updateRequired(check.id, event.currentTarget.checked)} type="checkbox" />必需检查</label>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <div class="mt-6 grid gap-4 md:grid-cols-3">
      <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><p class="text-xs font-bold text-slate-500">验证策略</p><TerminalSquare class="text-violet-500" size={17} /></div><p class="mt-5 text-lg font-bold text-slate-950">{configuredChecks.length} 项检查</p><p class="mt-2 text-xs text-slate-400">{project.rootPath ?? "尚未绑定项目根目录"}</p></article>
      <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><p class="text-xs font-bold text-slate-500">最近结果</p>{#if latestRun?.status === "passed"}<CheckCircle2 class="text-emerald-500" size={17} />{:else if latestRun?.status === "failed"}<XCircle class="text-red-500" size={17} />{:else}<CircleDashed class="text-slate-400" size={17} />{/if}</div><p class="mt-5 text-lg font-bold text-slate-950">{latestRun ? (latestRun.status === "passed" ? "验证通过" : latestRun.status === "failed" ? "验证失败" : latestRun.status === "running" ? "正在运行" : latestRun.status === "interrupted" ? "网关执行中断" : "已停止") : "暂无记录"}</p><p class="mt-2 text-xs text-slate-400">{latestRun ? `${passedCount}/${latestRun.checks.length} 项通过` : "运行后自动沉淀证据"}</p></article>
      <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><p class="text-xs font-bold text-slate-500">证据留存</p><History class="text-violet-500" size={17} /></div><p class="mt-5 text-lg font-bold text-slate-950">{runs.length} 次运行</p><p class="mt-2 text-xs text-slate-400">{persistenceMode === "gateway" ? "网关权威证据 · 最多 20 次" : "无可用权威证据"}</p></article>
    </div>

    {#if running || gatewayRunning}
      <section class="mt-6 rounded-2xl border border-violet-200 bg-violet-50 px-4 py-4 text-sm text-violet-800"><div class="flex items-center gap-2 font-bold"><Clock3 class="animate-pulse text-violet-500" size={16} />项目网关正在执行已保存的验证命令</div><p class="mt-1 text-xs leading-5 text-violet-600">退出码和有界输出仅由网关在运行结束后原子写入，浏览器不会创建终端或自行上报证据。</p></section>
    {/if}

    <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <div><h2 class="text-sm font-bold text-slate-900">验证历史</h2><p class="mt-1 text-xs text-slate-500">保存命令、退出码、耗时和有界输出，便于开发、评审和发布前复核。</p></div>
      <div class="mt-4 space-y-3" data-testid="validation-history">
        {#if runs.length === 0}
          <div class="rounded-2xl border border-dashed border-slate-300 px-6 py-10 text-center text-sm text-slate-500">尚无工程验证证据。配置命令后点击“运行验证”。</div>
        {:else}
          {#each runs as run (run.id)}
            <article class="overflow-hidden rounded-2xl border border-slate-200">
              <button class="flex w-full items-center gap-3 bg-slate-50 px-4 py-3 text-left" onclick={() => (expandedRunId = expandedRunId === run.id ? null : run.id)} type="button">
                {#if run.status === "passed"}<CheckCircle2 class="shrink-0 text-emerald-500" size={17} />{:else if run.status === "failed"}<XCircle class="shrink-0 text-red-500" size={17} />{:else}<CircleDashed class={`shrink-0 text-slate-400 ${run.status === "running" ? "animate-spin" : ""}`} size={17} />{/if}
                <span class="min-w-0 flex-1"><span class="block text-sm font-bold text-slate-800">{run.status === "passed" ? "验证通过" : run.status === "failed" ? "验证失败" : run.status === "running" ? "正在验证" : run.status === "interrupted" ? "网关执行中断" : "验证已停止"}</span><span class="mt-0.5 block truncate text-[11px] text-slate-400">{formatTime(run.startedAt)} · {run.branch ?? "无 Git 分支"} · {run.commit?.slice(0, 10) ?? "无提交"}</span></span>
                {#if expandedRunId === run.id}<ChevronUp size={16} />{:else}<ChevronDown size={16} />{/if}
              </button>
              {#if expandedRunId === run.id}
                <div class="space-y-3 border-t border-slate-200 p-4">
                  <div class="grid gap-2 rounded-xl bg-violet-50 px-3 py-2 text-[11px] text-violet-700 sm:grid-cols-3"><span>操作者：{run.operator?.profileId ?? "旧记录未绑定"}</span><span>版本：{run.commit?.slice(0, 12) ?? "未绑定"}</span><span class="truncate">摘要：{run.evidenceDigest?.slice(0, 16) ?? "旧记录无摘要"}</span></div>
                  {#each run.checks as check (check.id)}
                    <div class="rounded-xl border border-slate-200 p-3"><div class="flex flex-wrap items-center justify-between gap-2"><p class="text-xs font-bold text-slate-800">{check.label} · {check.status === "passed" ? "通过" : check.status === "failed" ? "失败" : check.status === "running" ? "运行中" : check.status === "cancelled" ? "已停止" : "等待"}</p><p class="text-[11px] text-slate-400">退出码 {check.exitCode ?? "—"} · {formatDuration(check.durationMs)}</p></div><code class="mt-2 block rounded-lg bg-slate-100 px-3 py-2 text-[11px] text-slate-700">{check.command}</code>{#if check.output}<pre class="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-5 text-slate-200">{check.output}</pre>{/if}</div>
                  {/each}
                </div>
              {/if}
            </article>
          {/each}
        {/if}
      </div>
    </section>
  </div>
</section>
