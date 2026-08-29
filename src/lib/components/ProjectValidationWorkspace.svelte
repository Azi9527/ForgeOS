<script lang="ts">
  import { onMount } from "svelte";
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
  import type {
    ProjectValidationCheck as ValidationCheck,
    ProjectValidationEvidence as ValidationEvidence,
    ProjectValidationRun as ValidationRun,
    SessionFolder
  } from "$lib/types";

  type StoredValidationState = {
    checks: ValidationCheck[];
    runs: ValidationRun[];
  };

  let { project, readOnly }: { project: SessionFolder; readOnly: boolean } = $props();

  let checks = $state<ValidationCheck[]>(defaultChecks());
  let runs = $state<ValidationRun[]>([]);
  let configurationOpen = $state(false);
  let expandedRunId = $state<string | null>(null);
  let running = $state(false);
  let cancelling = $state(false);
  let activeTerminalId = $state<string | null>(null);
  let activeOutput = $state("");
  let error = $state("");
  let persistenceMode = $state<"gateway" | "local" | "loading">("loading");
  let lifecycleRevision = $state<number | null>(null);
  let cancelRequested = false;

  const configuredChecks = $derived(checks.filter((check) => check.command.trim()));
  const latestRun = $derived(runs[0] ?? null);
  const passedCount = $derived(latestRun?.checks.filter((check) => check.status === "passed").length ?? 0);

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

  function storageKey() {
    return `forgeos:project-validation:v2:${project.projectId ?? "unregistered"}`;
  }

  function persist() {
    localStorage.setItem(storageKey(), JSON.stringify({ checks, runs: runs.slice(0, 20) } satisfies StoredValidationState));
  }

  function restore() {
    const raw = localStorage.getItem(storageKey());
    if (!raw) return;
    try {
      const stored = JSON.parse(raw) as Partial<StoredValidationState>;
      if (Array.isArray(stored.checks)) checks = stored.checks.slice(0, 12);
      if (Array.isArray(stored.runs)) {
        runs = stored.runs.slice(0, 20).map((run) =>
          run.status === "running"
            ? { ...run, status: "cancelled", finishedAt: Date.now(), checks: run.checks.map((check) => check.status === "running" ? { ...check, status: "cancelled" } : check) }
            : run
        );
      }
    } catch {
      error = "验证记录无法读取，已使用新的本地记录。";
    }
  }

  async function saveConfiguration() {
    checks = checks.map((check) => ({ ...check, command: check.command.trim() }));
    persist();
    if (persistenceMode === "gateway") {
      try {
        const lifecycle = await api.saveProjectValidation(projectId(), checks, lifecycleRevision);
        lifecycleRevision = lifecycle.revision;
        checks = lifecycle.validation.checks;
      } catch (cause) {
        error = cause instanceof Error ? cause.message : String(cause);
        return;
      }
    }
    configurationOpen = false;
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

  function stripAnsi(value: string) {
    return value.replace(/\u001b\[[0-?]*[ -/]*[@-~]/gu, "").replace(/\r/gu, "");
  }

  function boundedOutput(value: string, limit = 12_000) {
    const clean = stripAnsi(value);
    return clean.length > limit ? `…已截断早期输出…\n${clean.slice(-limit)}` : clean;
  }

  function commandPayload(command: string, marker: string, windows: boolean) {
    if (windows) {
      return `$global:LASTEXITCODE = 0; & { ${command} }; $forgeExit = if ($?) { if ($null -eq $LASTEXITCODE) { 0 } else { $LASTEXITCODE } } else { if ($null -eq $LASTEXITCODE) { 1 } else { $LASTEXITCODE } }; Write-Output "${marker}=$forgeExit"\r`;
    }
    return `{ ${command}; }; forge_exit=$?; printf '${marker}=%s\\n' "$forge_exit"\n`;
  }

  function updateActiveRun(run: ValidationRun) {
    runs = [run, ...runs.filter((entry) => entry.id !== run.id)].slice(0, 20);
    persist();
  }

  async function executeCheck(run: ValidationRun, check: ValidationEvidence) {
    const rootPath = project.rootPath;
    if (!rootPath) throw new Error("请先为项目绑定根目录。 ");
    const startedAt = Date.now();
    const marker = `__FORGEOS_VALIDATION_${run.id.replace(/\W/gu, "")}_${check.id.toUpperCase()}__`;
    const terminal = await api.createTerminal(rootPath, `ForgeOS 验证 · ${check.label}`);
    activeTerminalId = terminal.terminal.id;
    let snapshot = terminal.snapshot;
    activeOutput = boundedOutput(snapshot, 20_000);
    await api.sendTerminalInput(terminal.terminal.id, commandPayload(check.command, marker, /^[a-z]:[\\/]|^\\\\/iu.test(rootPath)));

    try {
      while (Date.now() - startedAt < 30 * 60 * 1000) {
        if (cancelRequested) {
          return { status: "cancelled" as const, exitCode: null, durationMs: Date.now() - startedAt, output: boundedOutput(snapshot) };
        }
        await new Promise((resolve) => window.setTimeout(resolve, 350));
        const current = await api.readTerminal(terminal.terminal.id);
        snapshot = current.snapshot;
        activeOutput = boundedOutput(snapshot, 20_000);
        const match = stripAnsi(snapshot).match(new RegExp(`${marker}=(-?\\d+)`, "u"));
        if (match) {
          const exitCode = Number(match[1]);
          return {
            status: exitCode === 0 ? "passed" as const : "failed" as const,
            exitCode,
            durationMs: Date.now() - startedAt,
            output: boundedOutput(snapshot.replace(new RegExp(`${marker}=-?\\d+`, "gu"), ""))
          };
        }
        if (current.terminal.status === "exited") {
          return { status: "failed" as const, exitCode: current.terminal.exitCode, durationMs: Date.now() - startedAt, output: boundedOutput(snapshot) };
        }
      }
      return { status: "failed" as const, exitCode: null, durationMs: Date.now() - startedAt, output: boundedOutput(`${snapshot}\n验证命令超过 30 分钟，已停止等待。`) };
    } finally {
      await api.closeTerminal(terminal.terminal.id).catch(() => undefined);
      activeTerminalId = null;
    }
  }

  async function runValidation() {
    if (running || readOnly) return;
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
    cancelRequested = false;
    error = "";
    activeOutput = "";
    let branch: string | null = null;
    let commit: string | null = null;
    try {
      const git = await api.getGitStatus(project.repoPath ?? project.rootPath);
      branch = git.branch;
      commit = git.commits[0]?.hash ?? null;
    } catch {
      // Validation may also run in a non-Git project.
    }
    let run: ValidationRun = {
      id: crypto.randomUUID(),
      startedAt: Date.now(),
      finishedAt: null,
      status: "running",
      rootPath: project.rootPath,
      branch,
      commit,
      operator: null,
      evidenceDigest: null,
      checks: configuredChecks.map((check) => ({ ...check, status: "pending", exitCode: null, durationMs: null, output: "" }))
    };
    expandedRunId = run.id;
    updateActiveRun(run);

    try {
      for (const evidence of run.checks) {
        if (cancelRequested) break;
        evidence.status = "running";
        run = { ...run, checks: [...run.checks] };
        updateActiveRun(run);
        try {
          const result = await executeCheck(run, evidence);
          Object.assign(evidence, result);
        } catch (cause) {
          evidence.status = cancelRequested ? "cancelled" : "failed";
          evidence.output = cause instanceof Error ? cause.message : String(cause);
        }
        run = { ...run, checks: [...run.checks] };
        updateActiveRun(run);
        if (evidence.required && evidence.status === "failed") break;
      }
      if (cancelRequested) {
        run.checks.forEach((check) => { if (check.status === "pending" || check.status === "running") check.status = "cancelled"; });
        run.status = "cancelled";
      } else {
        run.status = run.checks.some((check) => check.required && check.status !== "passed") ? "failed" : "passed";
      }
      run.finishedAt = Date.now();
      updateActiveRun({ ...run, checks: [...run.checks] });
      if (persistenceMode === "gateway") {
        try {
          const lifecycle = await api.recordProjectValidation(projectId(), run, lifecycleRevision);
          lifecycleRevision = lifecycle.revision;
          checks = lifecycle.validation.checks.length > 0 ? lifecycle.validation.checks : checks;
          runs = lifecycle.validation.runs;
          persist();
        } catch (cause) {
          error = `验证已完成，但网关证据写入失败：${cause instanceof Error ? cause.message : String(cause)}`;
        }
      }
    } finally {
      running = false;
      cancelling = false;
      activeOutput = "";
    }
  }

  async function cancelValidation() {
    if (!running) return;
    cancelling = true;
    cancelRequested = true;
    if (activeTerminalId) await api.closeTerminal(activeTerminalId).catch(() => undefined);
  }

  async function restoreLifecycle() {
    try {
      const lifecycle = await api.getProjectLifecycle(projectId());
      lifecycleRevision = lifecycle.revision;
      if (lifecycle.validation.checks.length > 0) checks = lifecycle.validation.checks;
      runs = lifecycle.validation.runs;
      persistenceMode = "gateway";
      persist();
    } catch {
      restore();
      persistenceMode = "local";
    }
  }

  onMount(() => {
    void restoreLifecycle();
  });
</script>

<section class="h-full overflow-y-auto bg-[#f7f8fb]" data-testid="project-validation-workspace">
  <div class="mx-auto w-full max-w-6xl px-6 py-8 lg:px-10 lg:py-10">
    <header class="flex flex-col gap-5 border-b border-slate-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="text-[10px] font-bold uppercase tracking-[0.22em] text-violet-600">ENGINEERING EVIDENCE</p>
        <h1 class="mt-2 text-2xl font-bold text-slate-950">验证与工程证据</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">在项目根目录中受控执行构建、测试和静态检查。证据绑定 Git 版本与操作者，并在项目网关中有界留存。</p>
        <p class="mt-2 text-[11px] font-semibold text-slate-400">{persistenceMode === "gateway" ? "项目网关持久化" : persistenceMode === "local" ? "旧网关兼容模式 · 本机暂存" : "正在读取项目证据"}</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700" onclick={() => (configurationOpen = !configurationOpen)} type="button"><Settings2 size={16} />配置流程</button>
        {#if running}
          <button class="inline-flex h-10 items-center gap-2 rounded-xl bg-red-600 px-4 text-sm font-bold text-white disabled:opacity-50" disabled={cancelling} onclick={cancelValidation} type="button"><Square size={14} />{cancelling ? "正在停止" : "停止验证"}</button>
        {:else}
          <button class="inline-flex h-10 items-center gap-2 rounded-xl bg-violet-600 px-4 text-sm font-bold text-white disabled:opacity-50" data-testid="validation-run" disabled={readOnly || configuredChecks.length === 0} onclick={runValidation} type="button"><Play size={15} />运行验证</button>
        {/if}
      </div>
    </header>

    {#if error}<div class="mt-5 flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={16} />{error}</div>{/if}

    {#if configurationOpen}
      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="validation-configuration">
        <div class="flex items-center justify-between gap-3"><div><h2 class="text-sm font-bold text-slate-900">项目验证流程</h2><p class="mt-1 text-xs text-slate-500">命令按顺序执行；必需检查失败后停止后续步骤。</p></div><button class="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold text-white" onclick={saveConfiguration} type="button"><Save size={14} />保存配置</button></div>
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
      <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><p class="text-xs font-bold text-slate-500">最近结果</p>{#if latestRun?.status === "passed"}<CheckCircle2 class="text-emerald-500" size={17} />{:else if latestRun?.status === "failed"}<XCircle class="text-red-500" size={17} />{:else}<CircleDashed class="text-slate-400" size={17} />{/if}</div><p class="mt-5 text-lg font-bold text-slate-950">{latestRun ? (latestRun.status === "passed" ? "验证通过" : latestRun.status === "failed" ? "验证失败" : latestRun.status === "running" ? "正在运行" : "已停止") : "暂无记录"}</p><p class="mt-2 text-xs text-slate-400">{latestRun ? `${passedCount}/${latestRun.checks.length} 项通过` : "运行后自动沉淀证据"}</p></article>
      <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div class="flex items-center justify-between"><p class="text-xs font-bold text-slate-500">证据留存</p><History class="text-violet-500" size={17} /></div><p class="mt-5 text-lg font-bold text-slate-950">{runs.length} 次运行</p><p class="mt-2 text-xs text-slate-400">{persistenceMode === "gateway" ? "项目级证据 · 最多 20 次" : "本机兼容记录 · 最多 20 次"}</p></article>
    </div>

    {#if running && activeOutput}
      <section class="mt-6 overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-sm"><div class="flex items-center gap-2 border-b border-slate-800 px-4 py-3 text-xs font-bold text-slate-300"><Clock3 class="animate-pulse text-violet-400" size={14} />实时验证输出</div><pre class="max-h-72 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5 text-slate-200">{activeOutput}</pre></section>
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
                <span class="min-w-0 flex-1"><span class="block text-sm font-bold text-slate-800">{run.status === "passed" ? "验证通过" : run.status === "failed" ? "验证失败" : run.status === "running" ? "正在验证" : "验证已停止"}</span><span class="mt-0.5 block truncate text-[11px] text-slate-400">{formatTime(run.startedAt)} · {run.branch ?? "无 Git 分支"} · {run.commit?.slice(0, 10) ?? "无提交"}</span></span>
                {#if expandedRunId === run.id}<ChevronUp size={16} />{:else}<ChevronDown size={16} />{/if}
              </button>
              {#if expandedRunId === run.id}
                <div class="space-y-3 border-t border-slate-200 p-4">
                  <div class="grid gap-2 rounded-xl bg-violet-50 px-3 py-2 text-[11px] text-violet-700 sm:grid-cols-3"><span>操作者：{run.operator?.profileId ?? "本机兼容记录"}</span><span>版本：{run.commit?.slice(0, 12) ?? "未绑定"}</span><span class="truncate">摘要：{run.evidenceDigest?.slice(0, 16) ?? "旧记录无摘要"}</span></div>
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
