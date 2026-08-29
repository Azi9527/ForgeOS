<script lang="ts">
  import { ArrowLeft, CheckCircle2, Code2, History, MessageSquare, Rocket, ServerCog, Settings2 } from "lucide-svelte";
  import type { SessionFolder } from "$lib/types";

  type Section = "development" | "code" | "validation" | "release" | "environment" | "audit" | "settings";

  let {
    project,
    active,
    embedded = false,
    onHome,
    onNavigate
  }: {
    project: SessionFolder;
    active: Section;
    embedded?: boolean;
    onHome: () => void;
    onNavigate: (section: Section) => void | Promise<void>;
  } = $props();

  const items = [
    { id: "development", label: "AI 开发", icon: MessageSquare },
    { id: "code", label: "代码", icon: Code2 },
    { id: "validation", label: "验证", icon: CheckCircle2 },
    { id: "release", label: "发布", icon: Rocket },
    { id: "environment", label: "环境", icon: ServerCog },
    { id: "audit", label: "审计", icon: History },
    { id: "settings", label: "设置", icon: Settings2 }
  ] as const;

  function displayProjectPath(path: string | null) {
    return path?.replace(/^\\\\\?\\/u, "") ?? "未绑定目录";
  }
</script>

<div class:project-command-bar--embedded={embedded} class="project-command-bar min-w-0 flex-1 border-b border-slate-200 bg-white px-3 py-2.5 sm:px-5" data-testid="project-navigation">
  <div class="flex min-w-0 items-center gap-3 overflow-x-auto">
    <button class="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg px-2 text-xs font-bold text-slate-500 transition hover:bg-slate-100 hover:text-slate-900" onclick={onHome} title="返回项目中心" type="button">
      <ArrowLeft size={15} />
      项目
    </button>
    <div class="h-7 w-px shrink-0 bg-slate-200"></div>
    <div class="mr-1 min-w-0 shrink-0">
      <p class="max-w-40 truncate text-[9px] font-bold uppercase tracking-[0.16em] text-violet-600">项目工作台</p>
      <p class="max-w-48 truncate text-sm font-black text-slate-950">{project.name}</p>
    </div>
    <nav class="ml-auto flex min-w-max items-center gap-1 rounded-xl bg-slate-100/80 p-1" aria-label="项目生命周期导航">
      {#each items as item (item.id)}
        {@const Icon = item.icon}
        <button
          aria-current={active === item.id ? "page" : undefined}
          class={`inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-bold transition ${active === item.id ? "bg-white text-violet-700 shadow-sm ring-1 ring-slate-200/70" : "text-slate-500 hover:bg-white/70 hover:text-slate-900"}`}
          onclick={() => onNavigate(item.id)}
          title={item.label}
          type="button"
        >
          <Icon size={14} />
          <span class="project-nav-label">{item.label}</span>
        </button>
      {/each}
    </nav>
  </div>
  <p class="mt-1 truncate pl-[4.65rem] text-[9px] text-slate-400" title={project.rootPath ?? "未绑定目录"}>{displayProjectPath(project.rootPath)}</p>
</div>

<style>
  .project-command-bar {
    background: linear-gradient(180deg, #fff 0%, #fbfbfd 100%);
  }

  .project-command-bar--embedded {
    border-bottom: 0;
  }

  @media (max-width: 1450px) {
    .project-nav-label {
      display: none;
    }

    button[aria-current="page"] .project-nav-label {
      display: inline;
    }
  }
</style>
