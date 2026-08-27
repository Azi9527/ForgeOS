<script lang="ts">
  import { AlertTriangle, FolderCog, GitBranch, MessageSquare, Pencil, Save, Search, Trash2 } from "lucide-svelte";

  import { getLocale } from "$lib/paraglide/runtime.js";
  import type { ModelOption, SessionFolder, SessionSummary } from "$lib/types";

  let {
    project,
    models,
    readOnly,
    onBindRoot,
    onSave,
    onRename,
    onRemove,
    onSearch,
    onOpenSession
  }: {
    project: SessionFolder;
    models: ModelOption[];
    readOnly: boolean;
    onBindRoot: () => void | Promise<void>;
    onSave: (model: string | null) => void | Promise<void>;
    onRename: (nextName: string) => void | Promise<void>;
    onRemove: () => void | Promise<void>;
    onSearch: (query: string) => Promise<SessionSummary[]>;
    onOpenSession: (sessionId: string, profileId: string | null) => void | Promise<void>;
  } = $props();

  let nameDraft = $state("");
  let modelDraft = $state("");
  let searchQuery = $state("");
  let searchResults = $state<SessionSummary[]>([]);
  let searchBusy = $state(false);
  let mutationBusy = $state(false);
  let error = $state("");
  let preview = $state<"rename" | "remove" | null>(null);

  const zh = $derived(getLocale() === "zh-Hans");

  $effect(() => {
    nameDraft = project.name;
    modelDraft = project.settings?.model ?? "";
    preview = null;
  });

  function describeError(value: unknown) {
    return value instanceof Error ? value.message : String(value);
  }

  async function saveSettings() {
    mutationBusy = true;
    error = "";
    try {
      await onSave(modelDraft || null);
    } catch (cause) {
      error = describeError(cause);
    } finally {
      mutationBusy = false;
    }
  }

  async function confirmRename() {
    const nextName = nameDraft.trim();
    if (!nextName || nextName === project.name) {
      preview = null;
      return;
    }
    mutationBusy = true;
    error = "";
    try {
      await onRename(nextName);
      preview = null;
    } catch (cause) {
      error = describeError(cause);
    } finally {
      mutationBusy = false;
    }
  }

  async function confirmRemove() {
    mutationBusy = true;
    error = "";
    try {
      await onRemove();
      preview = null;
    } catch (cause) {
      error = describeError(cause);
    } finally {
      mutationBusy = false;
    }
  }

  async function searchProject() {
    const query = searchQuery.trim();
    if (!query) {
      searchResults = [];
      return;
    }
    searchBusy = true;
    error = "";
    try {
      searchResults = await onSearch(query);
    } catch (cause) {
      error = describeError(cause);
    } finally {
      searchBusy = false;
    }
  }
</script>

<div class="mx-auto flex w-full max-w-6xl flex-col gap-5 p-5 sm:p-8" data-testid="project-workspace">
  <header class="flex flex-col gap-3 border-b pb-5 sm:flex-row sm:items-end sm:justify-between" style="border-color: var(--line);">
    <div class="min-w-0">
      <p class="text-[10px] font-bold uppercase tracking-[0.22em] text-violet-500">{zh ? "项目工作空间" : "Project workspace"}</p>
      <h2 class="mt-1 truncate text-2xl font-bold" style="color: var(--ink-strong);">{project.name}</h2>
      <p class="mt-1 text-sm" style="color: var(--muted);">{zh ? `${project.sessionCount} 条长期开发对话` : `${project.sessionCount} long-lived conversations`}</p>
    </div>
    <button class="rounded-xl border px-4 py-2 text-xs font-bold" disabled={readOnly || mutationBusy} onclick={onBindRoot} style="border-color: var(--line); color: var(--ink);" type="button">
      <FolderCog class="mr-2 inline" size={14} />{project.rootPath ? (zh ? "更换根目录" : "Change root") : (zh ? "绑定根目录" : "Bind root")}
    </button>
  </header>

  {#if error}
    <div class="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
  {/if}

  <div class="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(20rem,0.8fr)]">
    <section class="space-y-4 rounded-3xl border p-5 shadow-sm" style="border-color: var(--line); background: var(--panel-strong);">
      <div>
        <h3 class="text-sm font-bold" style="color: var(--ink-strong);">{zh ? "项目设置" : "Project settings"}</h3>
        <p class="mt-1 text-xs" style="color: var(--muted);">{zh ? "新对话继承根目录、Git 仓库和默认模型。安全与审批策略仍按对话确认。" : "New conversations inherit the root, Git repository, and model. Safety policies remain per-conversation."}</p>
      </div>
      <div class="grid gap-3">
        <label class="space-y-1.5">
          <span class="text-[10px] font-bold uppercase tracking-widest" style="color: var(--muted);">{zh ? "项目名称" : "Project name"}</span>
          <input bind:value={nameDraft} class="w-full rounded-xl border px-3 py-2.5 text-sm outline-none" disabled={readOnly || mutationBusy} style="border-color: var(--line); background: var(--panel-soft); color: var(--ink-strong);" />
        </label>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="rounded-2xl border p-3" style="border-color: var(--line); background: var(--panel-soft);">
            <p class="text-[10px] font-bold uppercase tracking-widest" style="color: var(--muted);">{zh ? "根目录" : "Root directory"}</p>
            <p class="mt-2 break-all text-xs font-semibold" style="color: var(--ink);">{project.rootPath ?? (zh ? "尚未绑定" : "Not bound")}</p>
          </div>
          <div class="rounded-2xl border p-3" style="border-color: var(--line); background: var(--panel-soft);">
            <p class="text-[10px] font-bold uppercase tracking-widest" style="color: var(--muted);"><GitBranch class="mr-1 inline" size={11} />Git</p>
            <p class="mt-2 break-all text-xs font-semibold" style="color: var(--ink);">{project.repoPath ?? (zh ? "未检测到仓库" : "Repository not detected")}</p>
          </div>
        </div>
        <label class="space-y-1.5">
          <span class="text-[10px] font-bold uppercase tracking-widest" style="color: var(--muted);">{zh ? "默认模型" : "Default model"}</span>
          <select bind:value={modelDraft} class="w-full rounded-xl border px-3 py-2.5 text-sm outline-none" disabled={readOnly || mutationBusy} style="border-color: var(--line); background: var(--panel-soft); color: var(--ink-strong);">
            <option value="">{zh ? "跟随全局默认" : "Use global default"}</option>
            {#each models as model (model.id)}
              <option value={model.id}>{model.displayName}</option>
            {/each}
          </select>
        </label>
      </div>
      <div class="flex flex-wrap gap-2 pt-1">
        <button class="rounded-xl bg-violet-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-50" disabled={readOnly || mutationBusy} onclick={saveSettings} type="button"><Save class="mr-2 inline" size={13} />{zh ? "保存设置" : "Save settings"}</button>
        <button class="rounded-xl border px-4 py-2 text-xs font-bold disabled:opacity-50" disabled={readOnly || mutationBusy || !nameDraft.trim() || nameDraft.trim() === project.name} onclick={() => (preview = "rename")} style="border-color: var(--line); color: var(--ink);" type="button"><Pencil class="mr-2 inline" size={13} />{zh ? "重命名" : "Rename"}</button>
        <button class="rounded-xl border border-red-200 px-4 py-2 text-xs font-bold text-red-700 disabled:opacity-50" disabled={readOnly || mutationBusy} onclick={() => (preview = "remove")} type="button"><Trash2 class="mr-2 inline" size={13} />{zh ? "移除项目" : "Remove project"}</button>
      </div>
      {#if preview}
        <div class={`rounded-2xl border p-4 ${preview === "remove" ? "border-red-200 bg-red-50" : "border-amber-200 bg-amber-50"}`} data-testid="project-mutation-preview">
          <div class="flex items-start gap-3">
            <AlertTriangle class={preview === "remove" ? "text-red-600" : "text-amber-600"} size={18} />
            <div class="min-w-0 flex-1">
              <p class="text-sm font-bold text-gray-900">{preview === "rename" ? (zh ? "迁移预览" : "Migration preview") : (zh ? "移除预览" : "Removal preview")}</p>
              <p class="mt-1 text-xs leading-5 text-gray-600">
                {#if preview === "rename"}
                  {zh ? `${project.sessionCount} 条对话将迁移到“${nameDraft.trim()}”；根目录、Git 绑定和最近对话保持不变。` : `${project.sessionCount} conversations will move to “${nameDraft.trim()}”; bindings and the recent conversation remain unchanged.`}
                {:else}
                  {zh ? `仅移除项目容器和项目标签。${project.sessionCount} 条对话不会删除，将回到“未归类对话”。` : `Only the container and project tag are removed. ${project.sessionCount} conversations remain and become unfiled.`}
                {/if}
              </p>
              <div class="mt-3 flex gap-2">
                <button class={`rounded-lg px-3 py-1.5 text-xs font-bold text-white ${preview === "remove" ? "bg-red-600" : "bg-amber-600"}`} disabled={mutationBusy} onclick={preview === "rename" ? confirmRename : confirmRemove} type="button">{zh ? "确认执行" : "Confirm"}</button>
                <button class="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-bold text-gray-600" disabled={mutationBusy} onclick={() => (preview = null)} type="button">{zh ? "取消" : "Cancel"}</button>
              </div>
            </div>
          </div>
        </div>
      {/if}
    </section>

    <section class="flex min-h-[28rem] flex-col rounded-3xl border p-5 shadow-sm" style="border-color: var(--line); background: var(--panel-strong);">
      <div>
        <h3 class="text-sm font-bold" style="color: var(--ink-strong);">{zh ? "项目对话搜索" : "Project conversation search"}</h3>
        <p class="mt-1 text-xs" style="color: var(--muted);">{zh ? "跨本项目全部长期对话搜索标题、摘要和完整内容。" : "Search titles, summaries, and full content across this project."}</p>
      </div>
      <div class="mt-4 flex gap-2">
        <input bind:value={searchQuery} class="min-w-0 flex-1 rounded-xl border px-3 py-2.5 text-sm outline-none" onkeydown={(event) => event.key === "Enter" && void searchProject()} placeholder={zh ? "搜索项目历史..." : "Search project history..."} style="border-color: var(--line); background: var(--panel-soft); color: var(--ink-strong);" type="search" />
        <button class="rounded-xl bg-gray-900 px-3 text-white disabled:opacity-50" disabled={searchBusy || !searchQuery.trim()} onclick={searchProject} title={zh ? "搜索" : "Search"} type="button"><Search class={searchBusy ? "animate-pulse" : ""} size={16} /></button>
      </div>
      <div class="mt-4 min-h-0 flex-1 space-y-2 overflow-y-auto">
        {#if searchResults.length === 0}
          <div class="flex h-full min-h-48 items-center justify-center rounded-2xl border border-dashed text-center text-xs" style="border-color: var(--line); color: var(--muted);">{searchQuery.trim() ? (zh ? "没有匹配的项目对话" : "No matching conversations") : (zh ? "输入关键词开始搜索" : "Enter a keyword to search")}</div>
        {:else}
          {#each searchResults as session (`${session.profileId ?? ""}:${session.id}`)}
            <button class="w-full rounded-2xl border p-3 text-left transition hover:-translate-y-px hover:shadow-sm" onclick={() => onOpenSession(session.id, session.profileId ?? null)} style="border-color: var(--line); background: var(--panel-soft);" type="button">
              <div class="flex items-start gap-2">
                <MessageSquare class="mt-0.5 shrink-0 text-violet-500" size={14} />
                <div class="min-w-0">
                  <p class="truncate text-sm font-bold" style="color: var(--ink-strong);">{session.name || session.preview || session.id}</p>
                  <p class="mt-1 line-clamp-2 text-xs leading-5" style="color: var(--muted);">{session.preview || (zh ? "无摘要" : "No summary")}</p>
                </div>
              </div>
            </button>
          {/each}
        {/if}
      </div>
    </section>
  </div>
</div>
