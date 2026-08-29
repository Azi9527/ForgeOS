<script lang="ts">
  import { CheckCircle2, History, RefreshCw, ShieldCheck, XCircle } from "lucide-svelte";

  import { api } from "$lib/api";
  import type { ProjectAuditEntry, SessionFolder } from "$lib/types";

  let { project }: { project: SessionFolder } = $props();

  let entries = $state<ProjectAuditEntry[]>([]);
  let loading = $state(false);
  let error = $state("");
  let loadSequence = 0;

  function formatTime(value: number) {
    const timestamp = value >= 1_000_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    }).format(timestamp);
  }

  function methodLabel(method: string) {
    const labels: Record<string, string> = {
      "projectLifecycle/validation/save": "更新验证方案",
      "projectLifecycle/validation/run": "网关执行项目验证",
      "projectLifecycle/validation/cancel": "停止项目验证",
      "projectLifecycle/governance/save": "更新项目治理策略",
      "projectLifecycle/release/save": "变更发布状态",
      "projectLifecycle/operations/save": "变更环境配置",
      "projectLifecycle/deployment/run": "网关执行部署",
      "projectLifecycle/environment/check": "网关执行健康检查",
      "projectLifecycle/operations/recover": "恢复中断的运维执行",
      "projectLifecycle/validation/recover": "恢复中断的验证执行",
      "projectArtifacts/upload": "上传并签名制品"
    };
    return labels[method] ?? method;
  }

  async function load(projectId = project.projectId) {
    const sequence = ++loadSequence;
    loading = true;
    error = "";
    try {
      if (!projectId) throw new Error("项目尚未完成 Project Registry V2 注册。");
      const response = await api.getProjectAudit(projectId, 200);
      if (sequence === loadSequence) {
        entries = response.entries;
      }
    } catch (cause) {
      if (sequence === loadSequence) {
        entries = [];
        error = cause instanceof Error ? cause.message : String(cause);
      }
    } finally {
      if (sequence === loadSequence) {
        loading = false;
      }
    }
  }

  $effect(() => {
    void load(project.projectId);
  });
</script>

<section class="h-full overflow-y-auto bg-[#f7f8fb]" data-testid="project-audit-workspace">
  <div class="mx-auto w-full max-w-6xl px-6 py-8 lg:px-10 lg:py-10">
    <header class="flex flex-col gap-5 border-b border-slate-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="text-[10px] font-bold tracking-[0.22em] text-violet-600">工程治理证据</p>
        <h1 class="mt-2 text-2xl font-bold text-slate-950">项目审计时间线</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">只展示属于当前 Project Context 的验证、制品、发布、环境和部署变更，形成可追溯的工程证据链。</p>
        <p class="mt-2 text-[11px] font-semibold text-slate-400">{project.name} · {project.rootPath ?? "未绑定项目目录"}</p>
      </div>
      <button class="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 disabled:opacity-50" disabled={loading} onclick={() => void load()} type="button"><RefreshCw class={loading ? "animate-spin" : ""} size={16} />刷新证据</button>
    </header>

    <div class="mt-6 grid gap-4 sm:grid-cols-3">
      <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">审计事件</p><p class="mt-3 text-2xl font-black text-slate-950">{entries.length}</p></article>
      <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">成功变更</p><p class="mt-3 text-2xl font-black text-emerald-600">{entries.filter((entry) => entry.ok).length}</p></article>
      <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">异常记录</p><p class="mt-3 text-2xl font-black text-rose-600">{entries.filter((entry) => !entry.ok).length}</p></article>
    </div>

    <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
      <div class="flex items-center gap-2"><ShieldCheck class="text-violet-600" size={18} /><h2 class="text-sm font-bold text-slate-900">工程操作证据</h2><span class="ml-auto text-xs text-slate-400">最近 {entries.length} 条</span></div>
      {#if error}
        <div class="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-700">项目审计网关暂不可用：{error}</div>
      {:else if !loading && entries.length === 0}
        <div class="mt-4 flex min-h-48 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 text-center"><History class="text-slate-300" size={28} /><p class="mt-3 text-sm font-bold text-slate-600">暂无项目审计记录</p><p class="mt-1 text-xs text-slate-400">执行验证、发布或环境操作后，证据会显示在这里。</p></div>
      {:else}
        <div class="mt-4 space-y-2">
          {#each entries as entry (entry.id)}
            <article class="flex items-start gap-3 rounded-xl border border-slate-200 px-4 py-3">
              {#if entry.ok}<CheckCircle2 class="mt-0.5 shrink-0 text-emerald-500" size={16} />{:else}<XCircle class="mt-0.5 shrink-0 text-rose-500" size={16} />{/if}
              <div class="min-w-0 flex-1"><p class="text-sm font-bold text-slate-800">{methodLabel(entry.method)}</p><p class="mt-1 break-all text-[11px] text-slate-400">{formatTime(entry.at)} · {entry.role}{entry.target ? ` · ${entry.target}` : ""}</p>{#if entry.error}<p class="mt-2 text-xs text-rose-600">{entry.error}</p>{/if}</div>
            </article>
          {/each}
        </div>
      {/if}
    </section>
  </div>
</section>
