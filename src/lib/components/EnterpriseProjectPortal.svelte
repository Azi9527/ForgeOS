<script lang="ts">
  import {
    Activity,
    ArrowRight,
    Boxes,
    FolderKanban,
    GitBranch,
    MessageSquare,
    Plus,
    Rocket,
    Search,
    ServerCog,
    Settings2
  } from "lucide-svelte";

  import type { SessionFolder, SessionSummary } from "$lib/types";

  let {
    projects,
    sessions,
    readOnly = false,
    onCreateProject,
    onOpenProject,
    onManageProject,
    onOpenSection
  }: {
    projects: SessionFolder[];
    sessions: SessionSummary[];
    readOnly?: boolean;
    onCreateProject: () => void | Promise<void>;
    onOpenProject: (project: SessionFolder) => void | Promise<void>;
    onManageProject: (project: SessionFolder) => void | Promise<void>;
    onOpenSection: (project: SessionFolder, section: "release" | "operations" | "settings") => void | Promise<void>;
  } = $props();

  let query = $state("");

  const filteredProjects = $derived.by(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const ordered = [...projects].sort((left, right) => {
      if (left.pinned !== right.pinned) {
        return left.pinned ? -1 : 1;
      }
      return (right.lastOpenedAt ?? right.updatedAt ?? 0) - (left.lastOpenedAt ?? left.updatedAt ?? 0);
    });
    if (!normalized) {
      return ordered;
    }
    return ordered.filter((project) =>
      [project.name, project.rootPath, project.repoPath]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLocaleLowerCase().includes(normalized))
    );
  });

  function runningCount(project: SessionFolder) {
    return sessions.filter(
      (session) => session.tags.includes(project.name) && ["active", "running"].includes(session.status)
    ).length;
  }

  function updatedLabel(project: SessionFolder) {
    const value = project.lastOpenedAt ?? project.updatedAt;
    if (!value) {
      return "尚未打开";
    }
    const timestamp = value >= 1_000_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat("zh-CN", {
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(new Date(timestamp));
  }
</script>

<section class="h-full overflow-y-auto bg-[#f6f7fb]" data-testid="enterprise-project-portal">
  <div class="mx-auto w-full max-w-[1440px] px-6 py-8 lg:px-10 lg:py-10">
    <header class="flex flex-col gap-6 border-b border-slate-200/80 pb-8 lg:flex-row lg:items-end lg:justify-between">
      <div class="min-w-0">
        <div class="mb-3 flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.24em] text-violet-600">
          <Boxes size={15} />
          ForgeOS Enterprise
        </div>
        <h1 class="text-3xl font-bold tracking-tight text-slate-950 lg:text-4xl">企业项目中心</h1>
        <p class="mt-3 max-w-2xl text-sm leading-6 text-slate-500">
          从一个项目进入完整的软件生命周期：持续 AI 开发、代码验证、版本发布与运行维护。
        </p>
      </div>
      <button
        class="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-violet-600 px-5 text-sm font-bold text-white shadow-sm transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
        disabled={readOnly}
        onclick={onCreateProject}
        type="button"
      >
        <Plus size={17} />
        新建项目
      </button>
    </header>

    <div class="mt-7 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p class="text-sm font-bold text-slate-900">全部项目</p>
        <p class="mt-1 text-xs text-slate-500">{projects.length} 个项目 · 开发、发布和运维统一管理</p>
      </div>
      <label class="relative block w-full sm:w-80">
        <Search class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          bind:value={query}
          class="h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm text-slate-800 outline-none transition placeholder:text-slate-400 focus:border-violet-400 focus:ring-2 focus:ring-violet-100"
          placeholder="搜索项目、目录或仓库..."
          type="search"
        />
      </label>
    </div>

    {#if filteredProjects.length > 0}
      <div class="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
        {#each filteredProjects as project (project.name)}
          {@const running = runningCount(project)}
          <article class="group overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:border-violet-200 hover:shadow-lg hover:shadow-violet-100/50" data-testid="project-folder-card">
            <button class="block w-full px-5 pb-4 pt-5 text-left" onclick={() => onOpenProject(project)} type="button">
              <div class="flex items-start justify-between gap-4">
                <span class="inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-600 ring-1 ring-violet-100">
                  <FolderKanban size={23} />
                </span>
                <span class={`rounded-full px-2.5 py-1 text-[10px] font-bold ${running > 0 ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                  {running > 0 ? `${running} 个执行中` : "工作区就绪"}
                </span>
              </div>
              <h2 class="mt-4 truncate text-lg font-bold text-slate-950">{project.name}</h2>
              <p class="mt-1 truncate text-xs text-slate-500">{project.rootPath ?? "尚未绑定项目目录"}</p>
              <div class="mt-5 grid grid-cols-3 gap-2">
                <div class="rounded-xl bg-slate-50 px-3 py-2.5">
                  <p class="text-[10px] font-bold uppercase tracking-wide text-slate-400">对话</p>
                  <p class="mt-1 text-sm font-bold text-slate-800">{project.sessionCount}</p>
                </div>
                <div class="rounded-xl bg-slate-50 px-3 py-2.5">
                  <p class="text-[10px] font-bold uppercase tracking-wide text-slate-400">版本</p>
                  <p class="mt-1 text-sm font-bold text-slate-800">待发布</p>
                </div>
                <div class="rounded-xl bg-slate-50 px-3 py-2.5">
                  <p class="text-[10px] font-bold uppercase tracking-wide text-slate-400">环境</p>
                  <p class="mt-1 text-sm font-bold text-slate-800">待接入</p>
                </div>
              </div>
              <div class="mt-4 flex items-center justify-between gap-3 text-xs text-slate-400">
                <span class="inline-flex min-w-0 items-center gap-1.5 truncate">
                  <GitBranch size={13} />
                  {project.repoPath ? project.repoPath.split(/[\\/]/u).filter(Boolean).at(-1) : "未识别 Git 仓库"}
                </span>
                <span class="shrink-0">{updatedLabel(project)}</span>
              </div>
            </button>

            <div class="grid grid-cols-4 border-t border-slate-100 bg-slate-50/70 p-2">
              <button class="inline-flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-bold text-slate-600 transition hover:bg-white hover:text-violet-700" onclick={() => onOpenProject(project)} type="button">
                <MessageSquare size={14} /> 开发
              </button>
              <button class="inline-flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-bold text-slate-600 transition hover:bg-white hover:text-violet-700" onclick={() => onOpenSection(project, "release")} type="button">
                <Rocket size={14} /> 发布
              </button>
              <button class="inline-flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-bold text-slate-600 transition hover:bg-white hover:text-violet-700" onclick={() => onOpenSection(project, "operations")} type="button">
                <ServerCog size={14} /> 运维
              </button>
              {#if project.managed === false}
                <button class="inline-flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-bold text-violet-700 transition hover:bg-white" disabled={readOnly} onclick={() => onManageProject(project)} type="button">
                  <Boxes size={14} /> 纳管
                </button>
              {:else}
                <button class="inline-flex items-center justify-center gap-1.5 rounded-lg px-2 py-2 text-xs font-bold text-slate-600 transition hover:bg-white hover:text-violet-700" onclick={() => onOpenSection(project, "settings")} type="button">
                  <Settings2 size={14} /> 设置
                </button>
              {/if}
            </div>
          </article>
        {/each}
      </div>
    {:else}
      <div class="mt-6 flex min-h-[360px] flex-col items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-white px-6 text-center">
        <span class="inline-flex h-16 w-16 items-center justify-center rounded-3xl bg-violet-50 text-violet-600">
          {#if projects.length === 0}<FolderKanban size={30} />{:else}<Search size={28} />{/if}
        </span>
        <h2 class="mt-5 text-lg font-bold text-slate-900">{projects.length === 0 ? "创建第一个企业项目" : "没有匹配的项目"}</h2>
        <p class="mt-2 max-w-md text-sm leading-6 text-slate-500">
          {projects.length === 0
            ? "绑定一个项目目录后，即可在同一个工作区持续开发，并逐步接入验证、发布和运维能力。"
            : "尝试使用项目名称、目录或仓库名称搜索。"}
        </p>
        {#if projects.length === 0}
          <button class="mt-5 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50" disabled={readOnly} onclick={onCreateProject} type="button">
            <Plus size={16} /> 新建项目
          </button>
        {/if}
      </div>
    {/if}

    <footer class="mt-8 grid gap-3 border-t border-slate-200/80 pt-6 sm:grid-cols-3">
      <div class="flex items-center gap-3 rounded-xl bg-white px-4 py-3 text-xs text-slate-500 ring-1 ring-slate-200/70"><Activity class="text-violet-500" size={16} /><span>持续 AI 开发会话</span></div>
      <div class="flex items-center gap-3 rounded-xl bg-white px-4 py-3 text-xs text-slate-500 ring-1 ring-slate-200/70"><Rocket class="text-violet-500" size={16} /><span>受控版本发布</span></div>
      <div class="flex items-center gap-3 rounded-xl bg-white px-4 py-3 text-xs text-slate-500 ring-1 ring-slate-200/70"><ServerCog class="text-violet-500" size={16} /><span>环境运行维护</span><ArrowRight class="ml-auto" size={14} /></div>
    </footer>
  </div>
</section>
