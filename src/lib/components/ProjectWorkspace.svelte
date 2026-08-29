<script lang="ts">
  import { AlertTriangle, DatabaseZap, FolderCog, GitBranch, MessageSquare, Pencil, RefreshCw, RotateCcw, Save, Search, ShieldCheck, Trash2 } from "lucide-svelte";

  import { api } from "$lib/api";
  import { getLocale } from "$lib/paraglide/runtime.js";
  import type { ModelOption, ProjectLifecycleMigrationPayload, SessionFolder, SessionSummary } from "$lib/types";

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
  let lifecycleMigration = $state<ProjectLifecycleMigrationPayload | null>(null);
  let lifecycleMigrationBusy = $state(false);
  let lifecycleMigrationError = $state("");
  let lifecycleSourceName = $state("");
  let lifecycleStrategy = $state<"preferLegacy" | "keepCurrent">("preferLegacy");

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

  async function loadLifecycleMigration() {
    if (!project.projectId) {
      lifecycleMigration = null;
      return;
    }
    lifecycleMigrationBusy = true;
    lifecycleMigrationError = "";
    try {
      lifecycleMigration = await api.getProjectLifecycleMigration(project.projectId);
      lifecycleSourceName = lifecycleMigration.commit?.sourceProjectName
        ?? lifecycleMigration.legacySources[0]?.projectName
        ?? "";
    } catch (cause) {
      lifecycleMigrationError = describeError(cause);
    } finally {
      lifecycleMigrationBusy = false;
    }
  }

  async function runLifecycleMigration(action: "commit" | "rollback" | "recover") {
    if (!project.projectId) return;
    lifecycleMigrationBusy = true;
    lifecycleMigrationError = "";
    try {
      lifecycleMigration = action === "commit"
        ? await api.commitProjectLifecycleMigration(project.projectId, lifecycleSourceName, lifecycleStrategy)
        : action === "rollback"
          ? await api.rollbackProjectLifecycleMigration(project.projectId)
          : await api.recoverProjectLifecycleMigration(project.projectId);
    } catch (cause) {
      lifecycleMigrationError = describeError(cause);
    } finally {
      lifecycleMigrationBusy = false;
    }
  }

  $effect(() => {
    if (project.projectId) void loadLifecycleMigration();
  });
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

  <section class="rounded-3xl border p-5 shadow-sm" data-testid="project-lifecycle-migration" style="border-color: var(--line); background: var(--panel-strong);">
    <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div class="flex min-w-0 items-start gap-3">
        <span class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-violet-50 text-violet-600"><DatabaseZap size={18} /></span>
        <div>
          <h3 class="text-sm font-bold" style="color: var(--ink-strong);">{zh ? "生命周期主键与旧数据恢复" : "Lifecycle identity and recovery"}</h3>
          <p class="mt-1 max-w-3xl text-xs leading-5" style="color: var(--muted);">{zh ? "验证、制品、发布、部署和审计统一归属于不可变 projectId。旧项目名称数据先预览冲突，再受控迁移；迁移中断可恢复，未产生后续变更时可安全回滚。" : "Validation, artifacts, releases, deployments, and audit records use the immutable projectId. Preview conflicts before migrating legacy name-based data, then recover or safely roll back."}</p>
          {#if project.projectId}<p class="mt-2 break-all font-mono text-[10px] text-violet-500">{project.projectId}</p>{/if}
        </div>
      </div>
      <button class="inline-flex h-9 items-center gap-2 rounded-xl border px-3 text-xs font-bold disabled:opacity-50" disabled={lifecycleMigrationBusy || !project.projectId} onclick={loadLifecycleMigration} style="border-color: var(--line); color: var(--ink);" type="button"><RefreshCw class={lifecycleMigrationBusy ? "animate-spin" : ""} size={13} />{zh ? "刷新状态" : "Refresh"}</button>
    </div>

    {#if lifecycleMigrationError}<div class="mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-700">{lifecycleMigrationError}</div>{/if}
    {#if lifecycleMigration}
      <div class="mt-4 rounded-2xl border p-4" class:border-amber-200={lifecycleMigration.status === "conflict" || lifecycleMigration.status === "recoveryRequired"} class:bg-amber-50={lifecycleMigration.status === "conflict" || lifecycleMigration.status === "recoveryRequired"} style={lifecycleMigration.status === "conflict" || lifecycleMigration.status === "recoveryRequired" ? "" : "border-color: var(--line); background: var(--panel-soft);"}>
        <div class="flex items-start gap-3">
          {#if lifecycleMigration.status === "migrated" || lifecycleMigration.status === "alreadyConsolidated" || lifecycleMigration.status === "notRequired"}<ShieldCheck class="mt-0.5 shrink-0 text-emerald-600" size={18} />{:else}<AlertTriangle class="mt-0.5 shrink-0 text-amber-600" size={18} />{/if}
          <div class="min-w-0 flex-1">
            <p class="text-sm font-bold" style="color: var(--ink-strong);">
              {lifecycleMigration.status === "notRequired" ? "已使用 projectId，无旧数据需要迁移" : lifecycleMigration.status === "ready" ? "发现旧项目生命周期数据" : lifecycleMigration.status === "conflict" ? "检测到 ID 数据与旧名称数据冲突" : lifecycleMigration.status === "recoveryRequired" ? "上次迁移未完成，需要恢复" : lifecycleMigration.status === "rolledBack" ? "迁移已回滚，可重新恢复" : "生命周期主键已统一"}
            </p>
            <p class="mt-1 text-xs leading-5" style="color: var(--muted);">旧来源 {lifecycleMigration.legacySources.length} 个 · 当前 ID 记录 {lifecycleMigration.current ? `revision ${lifecycleMigration.current.revision}` : "尚未建立"}</p>
            {#if lifecycleMigration.legacySources.length > 0}
              <div class="mt-3 grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
                <label class="text-[10px] font-bold" style="color: var(--muted);">旧数据来源
                  <select class="mt-1.5 w-full rounded-xl border px-3 py-2 text-xs" bind:value={lifecycleSourceName} disabled={lifecycleMigrationBusy || lifecycleMigration.status === "migrated"} style="border-color: var(--line); background: var(--panel-strong); color: var(--ink-strong);">
                    {#each lifecycleMigration.legacySources as source (source.projectName)}<option value={source.projectName}>{source.projectName} · 验证 {source.validationRuns} · 制品 {source.artifacts} · 发布 {source.releases} · 部署 {source.deployments}</option>{/each}
                  </select>
                </label>
                <label class="text-[10px] font-bold" style="color: var(--muted);">冲突处理
                  <select class="mt-1.5 w-full rounded-xl border px-3 py-2 text-xs" bind:value={lifecycleStrategy} disabled={lifecycleMigrationBusy || lifecycleMigration.status !== "conflict"} style="border-color: var(--line); background: var(--panel-strong); color: var(--ink-strong);"><option value="preferLegacy">以旧名称数据为准并重新签名制品</option><option value="keepCurrent">保留当前 projectId 数据</option></select>
                </label>
              </div>
            {/if}
            <div class="mt-3 flex flex-wrap gap-2">
              {#if lifecycleMigration.canMigrate}<button class="rounded-xl bg-violet-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-50" disabled={readOnly || lifecycleMigrationBusy || !lifecycleSourceName} onclick={() => runLifecycleMigration("commit")} type="button"><DatabaseZap class="mr-1.5 inline" size={13} />{lifecycleMigration.status === "rolledBack" ? "重新迁移" : "执行受控迁移"}</button>{/if}
              {#if lifecycleMigration.canRecover}<button class="rounded-xl bg-amber-600 px-4 py-2 text-xs font-bold text-white disabled:opacity-50" disabled={readOnly || lifecycleMigrationBusy} onclick={() => runLifecycleMigration("recover")} type="button"><RefreshCw class="mr-1.5 inline" size={13} />恢复未完成迁移</button>{/if}
              {#if lifecycleMigration.canRollback}<button class="rounded-xl border border-red-200 px-4 py-2 text-xs font-bold text-red-700 disabled:opacity-50" disabled={readOnly || lifecycleMigrationBusy} onclick={() => runLifecycleMigration("rollback")} type="button"><RotateCcw class="mr-1.5 inline" size={13} />回滚到迁移前</button>{/if}
            </div>
          </div>
        </div>
      </div>
    {/if}
  </section>
</div>
