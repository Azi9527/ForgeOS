<script lang="ts">
  import {
    BellRing,
    Bot,
    FolderKanban,
    Layout,
    MessageSquare,
    Monitor,
    Plug,
    Server,
    Settings2,
    Shield,
    Sparkles,
    Wand2
  } from "lucide-svelte";

  import type { EnterpriseSettingsTab } from "$lib/enterprise-navigation";
  import type { CodexRuntimeStatus, SessionSummary } from "$lib/types";

  let {
    activeView = null,
    activeSettingsTab = null,
    projectCount,
    conversationCount,
    recentSession = null,
    runtime = null,
    automationCount = 0,
    unreadNotifications = 0,
    onOpenView,
    onOpenSettings,
    onOpenSession
  }: {
    activeView?: "overview" | "projects" | null;
    activeSettingsTab?: EnterpriseSettingsTab | null;
    projectCount: number;
    conversationCount: number;
    recentSession?: SessionSummary | null;
    runtime?: CodexRuntimeStatus | null;
    automationCount?: number;
    unreadNotifications?: number;
    onOpenView: (view: "overview" | "projects") => void | Promise<void>;
    onOpenSettings: (tab: EnterpriseSettingsTab) => void | Promise<void>;
    onOpenSession: (sessionId: string, profileId: string | null) => void | Promise<void>;
  } = $props();
</script>

<aside class="enterprise-rail hidden h-full w-[19rem] shrink-0 flex-col border-r border-white/10 bg-[#0d1120] lg:flex" data-testid="enterprise-rail">
  <div class="flex h-[72px] items-center gap-3 border-b border-white/10 px-5">
    <span class="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-600 text-sm font-black text-white shadow-lg shadow-violet-950/40">F</span>
    <div><p class="font-black tracking-tight text-white">ForgeOS</p><p class="text-[9px] font-bold uppercase tracking-[0.16em] text-white/35">企业 AI 原生应用平台</p></div>
  </div>

  <nav class="flex-1 overflow-y-auto px-3 py-5 text-sm">
    <p class="nav-group">工作台</p>
    <button class:active-nav={activeView === "overview"} class="console-nav" onclick={() => onOpenView("overview")} type="button"><Layout size={17} />组织概览</button>
    <button class:active-nav={activeView === "projects"} class="console-nav" onclick={() => onOpenView("projects")} type="button"><FolderKanban size={17} />项目中心<span class="nav-count">{projectCount}</span></button>
    <button class="console-nav" disabled={!recentSession} onclick={() => recentSession && onOpenSession(recentSession.id, recentSession.profileId ?? null)} type="button"><MessageSquare size={17} />开发对话<span class="nav-count">{conversationCount}</span></button>

    <p class="nav-group mt-6">AI 资源</p>
    <button class:active-nav={activeSettingsTab === "defaults"} class="console-nav" onclick={() => onOpenSettings("defaults")} type="button"><Bot size={17} />模型与执行策略</button>
    <button class:active-nav={activeSettingsTab === "skills"} class="console-nav" onclick={() => onOpenSettings("skills")} type="button"><Sparkles size={17} />技能与专家</button>
    <button class:active-nav={activeSettingsTab === "apps" || activeSettingsTab === "plugins"} class="console-nav" onclick={() => onOpenSettings("apps")} type="button"><Monitor size={17} />应用与工具</button>
    <button class:active-nav={activeSettingsTab === "mcp"} class="console-nav" onclick={() => onOpenSettings("mcp")} type="button"><Plug size={17} />开放集成</button>

    <p class="nav-group mt-6">运行与治理</p>
    <button class:active-nav={activeSettingsTab === "processes"} class="console-nav" onclick={() => onOpenSettings("processes")} type="button"><Server size={17} />运行节点<span class:status-online={runtime?.installed} class="status-dot"></span></button>
    <button class:active-nav={activeSettingsTab === "automations"} class="console-nav" onclick={() => onOpenSettings("automations")} type="button"><Wand2 size={17} />自动化任务<span class="nav-count">{automationCount}</span></button>
    <button class:active-nav={activeSettingsTab === "audit"} class="console-nav" onclick={() => onOpenSettings("audit")} type="button"><Shield size={17} />安全与审计</button>
    <button class:active-nav={activeSettingsTab === "notifications"} class="console-nav" onclick={() => onOpenSettings("notifications")} type="button"><BellRing size={17} />通知中心{#if unreadNotifications > 0}<span class="nav-alert">{unreadNotifications}</span>{/if}</button>
  </nav>

  <div class="border-t border-white/10 p-4">
    <button class:active-settings={activeSettingsTab === "config"} class="settings-entry" onclick={() => onOpenSettings("config")} type="button"><Settings2 class="text-violet-300" size={17} /><span class="min-w-0"><span class="block text-xs font-bold">企业平台设置</span><span class="block truncate text-[10px] text-white/35">配置、账号与运行环境</span></span></button>
  </div>
</aside>

<style>
  .nav-group { padding:0 .75rem .45rem; font-size:10px; font-weight:800; text-transform:uppercase; letter-spacing:.18em; color:rgb(255 255 255 / .28); }
  .console-nav { display:flex; width:100%; align-items:center; gap:.7rem; border-radius:.7rem; padding:.66rem .75rem; color:rgb(255 255 255 / .58); font-weight:650; transition:.16s ease; }
  .console-nav:hover { background:rgb(139 92 246 / .12); color:white; }
  .console-nav.active-nav { background:linear-gradient(90deg,rgb(124 58 237 / .28),rgb(124 58 237 / .13)); color:white; box-shadow:inset 3px 0 #8b5cf6; }
  .console-nav:disabled { cursor:not-allowed; opacity:.45; }
  .nav-count { margin-left:auto; border-radius:999px; background:rgb(255 255 255 / .08); padding:.08rem .42rem; font-size:10px; color:rgb(255 255 255 / .5); }
  .nav-alert { margin-left:auto; min-width:1.25rem; border-radius:999px; background:#7c3aed; padding:.08rem .38rem; text-align:center; font-size:10px; color:white; }
  .status-dot { margin-left:auto; width:.5rem; height:.5rem; border-radius:999px; background:#cbd5e1; }
  .status-dot.status-online { background:#22c55e; box-shadow:0 0 0 3px rgb(34 197 94 / .12); }
  .settings-entry { display:flex; width:100%; align-items:center; gap:.75rem; border:1px solid rgb(255 255 255 / .1); border-radius:.75rem; background:rgb(255 255 255 / .045); padding:.75rem; text-align:left; color:rgb(255 255 255 / .7); transition:.16s ease; }
  .settings-entry:hover,.settings-entry.active-settings { border-color:rgb(167 139 250 / .4); background:rgb(139 92 246 / .12); color:white; }
</style>
