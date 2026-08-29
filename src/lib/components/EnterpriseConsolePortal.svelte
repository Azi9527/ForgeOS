<script lang="ts">
  import {
    Activity,
    ArrowRight,
    BellRing,
    Boxes,
    CheckCircle2,
    FolderKanban,
    GitBranch,
    History,
    MessageSquare,
    Plus,
    Plug,
    Rocket,
    Search,
    Server,
    ServerCog,
    Settings2,
    Sparkles,
    Wand2
  } from "lucide-svelte";

  import EnterpriseRail from "$lib/components/EnterpriseRail.svelte";
  import type { EnterpriseSettingsTab } from "$lib/enterprise-navigation";
  import type { CodexQuotaStatus, CodexRuntimeStatus, SessionFolder, SessionSummary } from "$lib/types";

  let {
    projects,
    sessions,
    runtime = null,
    quota = null,
    unreadNotifications = 0,
    automationCount = 0,
    initialView = "overview",
    readOnly = false,
    onCreateProject,
    onOpenProject,
    onManageProject,
    onOpenSection,
    onOpenSettings,
    onOpenSession
  }: {
    projects: SessionFolder[];
    sessions: SessionSummary[];
    runtime?: CodexRuntimeStatus | null;
    quota?: CodexQuotaStatus | null;
    unreadNotifications?: number;
    automationCount?: number;
    initialView?: "overview" | "projects";
    readOnly?: boolean;
    onCreateProject: () => void | Promise<void>;
    onOpenProject: (project: SessionFolder) => void | Promise<void>;
    onManageProject: (project: SessionFolder) => void | Promise<void>;
    onOpenSection: (project: SessionFolder, section: "release" | "environment" | "settings") => void | Promise<void>;
    onOpenSettings: (tab: EnterpriseSettingsTab) => void | Promise<void>;
    onOpenSession: (sessionId: string, profileId: string | null) => void | Promise<void>;
  } = $props();

  let activeView = $state<"overview" | "projects">("overview");
  let query = $state("");

  $effect(() => {
    activeView = initialView;
  });

  const activeSessions = $derived(sessions.filter((session) => ["active", "running"].includes(session.status)));
  const managedProjects = $derived(projects.filter((project) => project.managed !== false && Boolean(project.rootPath)));
  const totalConversations = $derived(projects.reduce((total, project) => total + project.sessionCount, 0));
  const orderedProjects = $derived.by(() =>
    [...projects].sort(
      (left, right) =>
        Number(right.pinned) - Number(left.pinned) ||
        (right.lastOpenedAt ?? right.updatedAt ?? 0) - (left.lastOpenedAt ?? left.updatedAt ?? 0)
    )
  );
  const filteredProjects = $derived.by(() => {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return orderedProjects;
    return orderedProjects.filter((project) =>
      [project.name, project.rootPath, project.repoPath]
        .filter((value): value is string => Boolean(value))
        .some((value) => value.toLocaleLowerCase().includes(normalized))
    );
  });
  const recentSessions = $derived([...sessions].sort((left, right) => right.updatedAt - left.updatedAt).slice(0, 5));

  function runningCount(project: SessionFolder) {
    return sessions.filter(
      (session) =>
        (project.projectId ? project.conversationIds?.includes(session.id) : session.tags.includes(project.name)) &&
        ["active", "running"].includes(session.status)
    ).length;
  }

  function updatedLabel(project: SessionFolder) {
    const value = project.lastOpenedAt ?? project.updatedAt;
    if (!value) return "尚未打开";
    const timestamp = value >= 1_000_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp));
  }

  function sessionUpdatedLabel(value: number) {
    const timestamp = value >= 1_000_000_000_000 ? value : value * 1000;
    return new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(timestamp));
  }

  function quotaLabel() {
    if (!quota?.available || !quota.fiveHour) return "等待数据";
    return `${Math.max(0, Math.round(quota.fiveHour.remainingPercent))}% 可用`;
  }
</script>

<section class="flex h-full min-h-0 bg-[#f5f7fb]" data-testid="enterprise-project-portal">
  <EnterpriseRail
    {runtime}
    {automationCount}
    {unreadNotifications}
    {activeView}
    projectCount={projects.length}
    conversationCount={totalConversations}
    recentSession={recentSessions[0] ?? null}
    onOpenView={(view) => {
      activeView = view;
    }}
    {onOpenSettings}
    {onOpenSession}
  />

  <main class="min-w-0 flex-1 overflow-y-auto">
    <div class="mx-auto w-full max-w-[1500px] px-5 py-6 sm:px-8 lg:px-10 lg:py-8">
      <div class="mb-5 flex gap-2 overflow-x-auto lg:hidden">
        <button class:mobile-active={activeView === "overview"} class="mobile-console-nav" onclick={() => (activeView = "overview")} type="button">组织概览</button>
        <button class:mobile-active={activeView === "projects"} class="mobile-console-nav" onclick={() => (activeView = "projects")} type="button">项目中心</button>
        <button class="mobile-console-nav" onclick={() => onOpenSettings("skills")} type="button">AI 资源</button>
        <button class="mobile-console-nav" onclick={() => onOpenSettings("processes")} type="button">运行治理</button>
      </div>

      {#if activeView === "overview"}
        <header class="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div><p class="text-[11px] font-bold uppercase tracking-[0.22em] text-violet-600">ForgeOS 企业平台</p><h1 class="mt-2 text-3xl font-black tracking-tight text-slate-950">企业 AI 原生应用平台</h1><p class="mt-2 max-w-3xl text-sm leading-6 text-slate-500">统一组织项目、AI 能力、开发会话、运行资源与工程治理，从业务构想到发布运维持续协作。</p></div>
          <button class="primary-action" disabled={readOnly} onclick={onCreateProject} type="button"><Plus size={17} />新建项目</button>
        </header>

        <div class="mt-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div class="metric-card"><span class="metric-icon bg-violet-50 text-violet-600"><FolderKanban size={18} /></span><div><p>企业项目</p><strong>{projects.length}</strong><small>{managedProjects.length} 个已绑定目录</small></div></div>
          <div class="metric-card"><span class="metric-icon bg-emerald-50 text-emerald-600"><Activity size={18} /></span><div><p>实时执行</p><strong>{activeSessions.length}</strong><small>{totalConversations} 条持续对话</small></div></div>
          <div class="metric-card"><span class="metric-icon bg-blue-50 text-blue-600"><ServerCog size={18} /></span><div><p>运行节点</p><strong>{runtime?.installed ? "在线" : "未就绪"}</strong><small>{runtime?.version ?? "等待运行时信息"}</small></div></div>
          <div class="metric-card"><span class="metric-icon bg-amber-50 text-amber-600"><CheckCircle2 size={18} /></span><div><p>AI 资源额度</p><strong>{quotaLabel()}</strong><small>{quota?.plan ?? "尚未识别套餐"}</small></div></div>
        </div>

        <div class="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div class="space-y-6">
            <section class="console-panel">
              <div class="panel-heading"><div><p class="panel-eyebrow">快速开始</p><h2>今天要推进什么？</h2></div></div>
              <div class="grid gap-3 md:grid-cols-2">
                <button class="launch-card" disabled={readOnly} onclick={onCreateProject} type="button"><span class="launch-icon bg-violet-600 text-white"><Plus size={20} /></span><span><strong>创建 AI 原生应用项目</strong><small>建立独立目录并进入持续开发工作区</small></span><ArrowRight size={16} /></button>
                <button class="launch-card" disabled={!orderedProjects[0]} onclick={() => orderedProjects[0] && onOpenProject(orderedProjects[0])} type="button"><span class="launch-icon bg-blue-50 text-blue-600"><MessageSquare size={20} /></span><span><strong>接续最近项目</strong><small>{orderedProjects[0]?.name ?? "暂无可接续项目"}</small></span><ArrowRight size={16} /></button>
                <button class="launch-card" onclick={() => onOpenSettings("skills")} type="button"><span class="launch-icon bg-fuchsia-50 text-fuchsia-600"><Sparkles size={20} /></span><span><strong>配置 AI 能力</strong><small>管理模型、技能、专家与工程工具</small></span><ArrowRight size={16} /></button>
                <button class="launch-card" onclick={() => onOpenSettings("automations")} type="button"><span class="launch-icon bg-amber-50 text-amber-600"><Wand2 size={20} /></span><span><strong>编排自动化任务</strong><small>{automationCount} 个任务已配置</small></span><ArrowRight size={16} /></button>
              </div>
            </section>

            <section class="console-panel">
              <div class="panel-heading"><div><p class="panel-eyebrow">项目工作区</p><h2>最近项目</h2></div><button class="text-action" onclick={() => (activeView = "projects")} type="button">查看全部 <ArrowRight size={14} /></button></div>
              <div class="divide-y divide-slate-100">
                {#each orderedProjects.slice(0, 5) as project (project.projectId ?? project.name)}
                  <button class="project-row" onclick={() => onOpenProject(project)} type="button"><span class="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-50 text-violet-600"><FolderKanban size={19} /></span><span class="min-w-0 flex-1"><strong>{project.name}</strong><small>{project.rootPath ?? "尚未建立独立项目目录"}</small></span><span class="hidden text-right sm:block"><strong>{project.sessionCount} 条对话</strong><small>{updatedLabel(project)}</small></span><ArrowRight class="text-slate-300" size={16} /></button>
                {/each}
                {#if projects.length === 0}<div class="py-12 text-center text-sm text-slate-400">创建第一个项目后，它会显示在这里。</div>{/if}
              </div>
            </section>
          </div>

          <aside class="space-y-6">
            <section class="console-panel p-5"><div class="panel-heading compact-heading"><div><p class="panel-eyebrow">平台状态</p><h2>运行与治理</h2></div><span class={`health-badge ${runtime?.installed ? "health-online" : "health-offline"}`}>{runtime?.installed ? "服务正常" : "需要检查"}</span></div><div class="mt-4 space-y-2"><button class="status-row" onclick={() => onOpenSettings("processes")} type="button"><Server size={16} /><span>运行节点</span><strong>{runtime?.installed ? "已连接" : "未连接"}</strong></button><button class="status-row" onclick={() => onOpenSettings("notifications")} type="button"><BellRing size={16} /><span>待处理通知</span><strong>{unreadNotifications}</strong></button><button class="status-row" onclick={() => onOpenSettings("audit")} type="button"><History size={16} /><span>安全审计</span><strong>可查询</strong></button><button class="status-row" onclick={() => onOpenSettings("mcp")} type="button"><Plug size={16} /><span>开放集成</span><strong>管理</strong></button></div></section>

            <section class="console-panel p-5"><div class="panel-heading compact-heading"><div><p class="panel-eyebrow">持续执行</p><h2>最近开发对话</h2></div></div><div class="mt-3 space-y-1">{#each recentSessions as session (session.id)}<button class="session-row" onclick={() => onOpenSession(session.id, session.profileId ?? null)} type="button"><span class={`session-dot ${["active", "running"].includes(session.status) ? "bg-emerald-500" : "bg-slate-300"}`}></span><span class="min-w-0 flex-1"><strong>{session.name ?? session.preview ?? "未命名开发对话"}</strong><small>{sessionUpdatedLabel(session.updatedAt)}</small></span></button>{/each}{#if recentSessions.length === 0}<p class="py-8 text-center text-xs text-slate-400">暂无开发对话</p>{/if}</div></section>
          </aside>
        </div>
      {:else}
        <header class="flex flex-col gap-5 border-b border-slate-200/80 pb-7 lg:flex-row lg:items-end lg:justify-between"><div><p class="text-[11px] font-bold uppercase tracking-[0.22em] text-violet-600">项目工作区</p><h1 class="mt-2 text-3xl font-black tracking-tight text-slate-950">企业项目中心</h1><p class="mt-2 text-sm text-slate-500">每个项目拥有独立目录、持续开发对话、发布流程与运行环境。</p></div><button class="primary-action" disabled={readOnly} onclick={onCreateProject} type="button"><Plus size={17} />新建项目</button></header>
        <div class="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between"><div><p class="text-sm font-bold text-slate-900">全部项目</p><p class="mt-1 text-xs text-slate-500">{projects.length} 个项目 · {activeSessions.length} 个执行中</p></div><label class="relative block w-full sm:w-96"><Search class="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} /><input bind:value={query} class="h-10 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-100" placeholder="搜索项目、目录或仓库..." type="search" /></label></div>

        {#if filteredProjects.length > 0}
          <div class="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2 2xl:grid-cols-3">
            {#each filteredProjects as project (project.projectId ?? project.name)}
              {@const running = runningCount(project)}
              <article class="project-card" data-testid="project-folder-card" data-project-id={project.projectId ?? undefined}><button class="block w-full px-5 pb-4 pt-5 text-left" onclick={() => onOpenProject(project)} type="button"><div class="flex items-start justify-between gap-4"><span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-50 text-violet-600 ring-1 ring-violet-100"><FolderKanban size={23} /></span><span class={`rounded-full px-2.5 py-1 text-[10px] font-bold ${running > 0 ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{running > 0 ? `${running} 个执行中` : project.managed === false ? "等待纳管" : "工作区就绪"}</span></div><h2 class="mt-4 truncate text-lg font-bold text-slate-950">{project.name}</h2><p class="mt-1 truncate text-xs text-slate-500">{project.rootPath ?? "尚未建立独立项目目录"}</p><div class="mt-5 grid grid-cols-3 gap-2"><div class="project-stat"><p>对话</p><strong>{project.sessionCount}</strong></div><div class="project-stat"><p>版本</p><strong>待发布</strong></div><div class="project-stat"><p>环境</p><strong>待接入</strong></div></div><div class="mt-4 flex items-center justify-between gap-3 text-xs text-slate-400"><span class="inline-flex min-w-0 items-center gap-1.5 truncate"><GitBranch size={13} />{project.repoPath ? project.repoPath.split(/[\\/]/u).filter(Boolean).at(-1) : "未识别 Git 仓库"}</span><span>{updatedLabel(project)}</span></div></button><div class="grid grid-cols-4 border-t border-slate-100 bg-slate-50/70 p-2"><button class="project-action" onclick={() => onOpenProject(project)} type="button"><MessageSquare size={14} />开发</button><button class="project-action" onclick={() => onOpenSection(project, "release")} type="button"><Rocket size={14} />发布</button><button class="project-action" onclick={() => onOpenSection(project, "environment")} type="button"><ServerCog size={14} />环境</button>{#if project.managed === false}<button class="project-action text-violet-700" disabled={readOnly} onclick={() => onManageProject(project)} type="button"><Boxes size={14} />纳管</button>{:else}<button class="project-action" onclick={() => onOpenSection(project, "settings")} type="button"><Settings2 size={14} />设置</button>{/if}</div></article>
            {/each}
          </div>
        {:else}
          <div class="mt-6 flex min-h-[360px] flex-col items-center justify-center rounded-3xl border border-dashed border-slate-300 bg-white px-6 text-center"><span class="flex h-16 w-16 items-center justify-center rounded-3xl bg-violet-50 text-violet-600">{#if projects.length === 0}<FolderKanban size={30} />{:else}<Search size={28} />{/if}</span><h2 class="mt-5 text-lg font-bold text-slate-900">{projects.length === 0 ? "创建第一个企业项目" : "没有匹配的项目"}</h2><p class="mt-2 max-w-md text-sm leading-6 text-slate-500">项目将获得独立目录和持续开发工作区，并可逐步接入验证、发布与运维。</p>{#if projects.length === 0}<button class="primary-action mt-5" disabled={readOnly} onclick={onCreateProject} type="button"><Plus size={16} />新建项目</button>{/if}</div>
        {/if}
      {/if}
    </div>
  </main>
</section>

<style>
  .mobile-console-nav { flex:none; border:1px solid #e2e8f0; border-radius:.7rem; background:white; padding:.55rem .85rem; font-size:.75rem; font-weight:700; color:#64748b; }
  .mobile-console-nav.mobile-active { border-color:#c4b5fd; background:#ede9fe; color:#6d28d9; }
  .primary-action { display:inline-flex; min-height:2.7rem; align-items:center; justify-content:center; gap:.5rem; border-radius:.75rem; background:#7c3aed; padding:.65rem 1.15rem; font-size:.875rem; font-weight:800; color:white; box-shadow:0 8px 22px rgb(124 58 237 / .18); }
  .primary-action:hover { background:#6d28d9; }
  .primary-action:disabled { cursor:not-allowed; opacity:.5; }
  .metric-card { display:flex; min-height:112px; align-items:center; gap:1rem; border:1px solid #e2e8f0; border-radius:1rem; background:white; padding:1rem; box-shadow:0 1px 2px rgb(15 23 42 / .03); }
  .metric-icon { display:flex; width:2.6rem; height:2.6rem; flex:none; align-items:center; justify-content:center; border-radius:.8rem; }
  .metric-card p { font-size:11px; font-weight:750; color:#64748b; }
  .metric-card strong { display:block; margin-top:.15rem; font-size:1.25rem; color:#0f172a; }
  .metric-card small { display:block; margin-top:.15rem; max-width:160px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:10px; color:#94a3b8; }
  .console-panel { overflow:hidden; border:1px solid #e2e8f0; border-radius:1rem; background:white; box-shadow:0 1px 3px rgb(15 23 42 / .035); }
  .panel-heading { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:1.1rem 1.25rem; }
  .panel-heading.compact-heading { padding:0; }
  .panel-heading h2 { margin-top:.15rem; font-size:1rem; font-weight:800; color:#0f172a; }
  .panel-eyebrow { font-size:9px; font-weight:800; text-transform:uppercase; letter-spacing:.18em; color:#8b5cf6; }
  .launch-card { display:flex; min-height:92px; align-items:center; gap:.8rem; border:1px solid #e2e8f0; border-radius:.85rem; margin:0 1.1rem 1.1rem; padding:1rem; text-align:left; transition:.16s ease; }
  .launch-card:hover { border-color:#c4b5fd; background:#faf8ff; transform:translateY(-1px); }
  .launch-card:disabled { cursor:not-allowed; opacity:.5; }
  .launch-icon { display:flex; width:2.6rem; height:2.6rem; flex:none; align-items:center; justify-content:center; border-radius:.8rem; }
  .launch-card span:nth-child(2) { min-width:0; flex:1; }
  .launch-card strong,.project-row strong,.session-row strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.78rem; color:#1e293b; }
  .launch-card small,.project-row small,.session-row small { display:block; margin-top:.25rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.65rem; color:#94a3b8; }
  .text-action { display:inline-flex; align-items:center; gap:.3rem; font-size:.7rem; font-weight:750; color:#7c3aed; }
  .project-row { display:flex; width:100%; align-items:center; gap:.8rem; padding:.8rem 1.2rem; text-align:left; transition:.15s ease; }
  .project-row:hover,.session-row:hover { background:#f8fafc; }
  .status-row { display:flex; width:100%; align-items:center; gap:.65rem; border-radius:.7rem; padding:.65rem .7rem; color:#64748b; }
  .status-row:hover { background:#f8fafc; }
  .status-row span { flex:1; text-align:left; font-size:.72rem; }
  .status-row strong { font-size:.68rem; color:#334155; }
  .health-badge { border-radius:999px; padding:.25rem .55rem; font-size:9px; font-weight:800; }
  .health-online { background:#dcfce7; color:#15803d; }
  .health-offline { background:#fee2e2; color:#b91c1c; }
  .session-row { display:flex; width:100%; align-items:center; gap:.65rem; border-radius:.7rem; padding:.55rem .7rem; text-align:left; }
  .session-dot { width:.45rem; height:.45rem; flex:none; border-radius:999px; }
  .project-card { overflow:hidden; border:1px solid #e2e8f0; border-radius:1rem; background:white; box-shadow:0 1px 3px rgb(15 23 42 / .04); transition:.18s ease; }
  .project-card:hover { transform:translateY(-2px); border-color:#c4b5fd; box-shadow:0 12px 28px rgb(124 58 237 / .08); }
  .project-stat { border-radius:.7rem; background:#f8fafc; padding:.65rem .7rem; }
  .project-stat p { font-size:9px; font-weight:800; text-transform:uppercase; color:#94a3b8; }
  .project-stat strong { display:block; margin-top:.2rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:.72rem; color:#334155; }
  .project-action { display:inline-flex; align-items:center; justify-content:center; gap:.35rem; border-radius:.55rem; padding:.5rem; font-size:.68rem; font-weight:750; color:#475569; }
  .project-action:hover { background:white; color:#6d28d9; }
</style>
