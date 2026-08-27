<script lang="ts">
  import { ArrowLeft, CheckCircle2, Code2, MessageSquare, Rocket, ServerCog, Settings2 } from "lucide-svelte";
  import type { SessionFolder } from "$lib/types";

  type Section = "development" | "code" | "validation" | "release" | "operations" | "settings";

  let {
    project,
    active,
    onHome,
    onNavigate
  }: {
    project: SessionFolder;
    active: Section;
    onHome: () => void;
    onNavigate: (section: Section) => void | Promise<void>;
  } = $props();

  const items = [
    { id: "development", label: "AI 开发", icon: MessageSquare },
    { id: "code", label: "代码", icon: Code2 },
    { id: "validation", label: "验证", icon: CheckCircle2 },
    { id: "release", label: "发布", icon: Rocket },
    { id: "operations", label: "运维", icon: ServerCog },
    { id: "settings", label: "设置", icon: Settings2 }
  ] as const;
</script>

<div class="border-b border-slate-200 bg-white px-3 py-2 sm:px-5" data-testid="project-navigation">
  <div class="flex min-w-0 items-center gap-2 overflow-x-auto">
    <button class="inline-flex h-9 shrink-0 items-center gap-2 rounded-lg px-2.5 text-xs font-bold text-slate-500 transition hover:bg-slate-100 hover:text-slate-900" onclick={onHome} type="button">
      <ArrowLeft size={15} />
      项目中心
    </button>
    <div class="mx-1 h-5 w-px shrink-0 bg-slate-200"></div>
    <div class="mr-2 min-w-0 shrink-0">
      <p class="max-w-44 truncate text-xs font-bold text-slate-900">{project.name}</p>
      <p class="max-w-44 truncate text-[10px] text-slate-400">{project.rootPath ?? "未绑定目录"}</p>
    </div>
    <nav class="flex min-w-max items-center gap-1" aria-label="项目生命周期导航">
      {#each items as item (item.id)}
        {@const Icon = item.icon}
        <button
          aria-current={active === item.id ? "page" : undefined}
          class={`inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-xs font-bold transition ${active === item.id ? "bg-violet-50 text-violet-700 ring-1 ring-violet-100" : "text-slate-500 hover:bg-slate-100 hover:text-slate-900"}`}
          onclick={() => onNavigate(item.id)}
          type="button"
        >
          <Icon size={14} />
          {item.label}
        </button>
      {/each}
    </nav>
  </div>
</div>
