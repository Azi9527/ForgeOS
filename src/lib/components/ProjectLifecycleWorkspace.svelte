<script lang="ts">
  import {
    AlertCircle, CheckCircle2, CircleDashed, Download, ExternalLink, FileCheck2,
    HeartPulse, History, PackageCheck, Play, Plus, RotateCcw, Rocket, Save,
    ServerCog, ShieldCheck, TerminalSquare, Upload, XCircle
  } from "lucide-svelte";
  import { api } from "$lib/api";
  import type {
    ProjectArtifact, ProjectEnvironment,
    ProjectGovernance, ProjectLifecyclePayload, ProjectRelease, SessionFolder
  } from "$lib/types";

  let {
    project, surface, onConfigure, readOnly = false
  }: {
    project: SessionFolder;
    surface: "validation" | "release" | "operations";
    onConfigure: () => void;
    readOnly?: boolean;
  } = $props();

  let lifecycle = $state<ProjectLifecyclePayload | null>(null);
  let persistenceMode = $state<"gateway" | "unavailable" | "loading">("loading");
  let busy = $state(false);
  let error = $state("");
  let artifactVersion = $state("");
  let artifactFile = $state<File | null>(null);
  let releaseTargetEnvironmentId = $state("");
  let environmentName = $state("");
  let environmentKind = $state<ProjectEnvironment["kind"]>("development");
  let environmentUrl = $state("");
  let environmentAdapter = $state<NonNullable<ProjectEnvironment["adapter"]>>("localCommand");
  let deployCommand = $state("");
  let githubRepository = $state("");
  let githubWorkflow = $state("");
  let githubRef = $state("main");
  let healthCommand = $state("");
  let standardApprovals = $state(1);
  let productionApprovals = $state(2);
  let maxArtifacts = $state(50);
  let maxAgeDays = $state(180);
  let notifyApprovalRequested = $state(true);
  let notifyReleaseCompleted = $state(true);
  let notifyRollbackCompleted = $state(true);
  let notifyDeploymentFailed = $state(true);
  let loadGeneration = 0;
  let mutationSequence = 0;
  let activeMutationToken: number | null = null;

  type MutationContext = Readonly<{
    projectId: string;
    lifecycleSnapshot: ProjectLifecyclePayload;
    loadGeneration: number;
    mutationToken: number;
  }>;

  const artifacts = $derived(lifecycle?.release.artifacts ?? []);
  const releases = $derived(lifecycle?.release.releases ?? []);
  const environments = $derived(lifecycle?.operations.environments ?? []);
  const deployments = $derived(lifecycle?.operations.deployments ?? []);
  const latestPassedValidation = $derived(lifecycle?.validation.runs.find((run) => run.status === "passed") ?? null);
  const latestRelease = $derived(releases[0] ?? null);
  const selectedReleaseEnvironment = $derived(
    environments.find((environment) => environment.id === releaseTargetEnvironmentId) ?? null
  );

  function applyLifecycle(nextLifecycle: ProjectLifecyclePayload) {
    lifecycle = nextLifecycle;
    persistenceMode = "gateway";
    error = "";
    standardApprovals = nextLifecycle.governance.approvalPolicy.standardApprovals;
    productionApprovals = nextLifecycle.governance.approvalPolicy.productionApprovals;
    maxArtifacts = nextLifecycle.governance.artifactRetention.maxArtifacts;
    maxAgeDays = nextLifecycle.governance.artifactRetention.maxAgeDays;
    notifyApprovalRequested = nextLifecycle.governance.notificationRoutes.approvalRequested;
    notifyReleaseCompleted = nextLifecycle.governance.notificationRoutes.releaseCompleted;
    notifyRollbackCompleted = nextLifecycle.governance.notificationRoutes.rollbackCompleted;
    notifyDeploymentFailed = nextLifecycle.governance.notificationRoutes.deploymentFailed;
  }

  async function loadLifecycle(targetProjectId: string, generation: number) {
    try {
      const nextLifecycle = await api.getProjectLifecycle(targetProjectId);
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      applyLifecycle(nextLifecycle);
    } catch (cause) {
      if (generation !== loadGeneration || project.projectId !== targetProjectId) return;
      lifecycle = null;
      persistenceMode = "unavailable";
      error = cause instanceof Error ? cause.message : String(cause);
    }
  }

  function mutationIsCurrent(context: MutationContext) {
    return project.projectId === context.projectId
      && loadGeneration === context.loadGeneration
      && activeMutationToken === context.mutationToken;
  }

  function applyMutationLifecycle(context: MutationContext, nextLifecycle: ProjectLifecyclePayload) {
    if (!mutationIsCurrent(context)) return false;
    applyLifecycle(nextLifecycle);
    return true;
  }

  function isLifecycleConflict(message: string) {
    return /\b(?:changed|conflict|revision)\b|\b409\b|已变更|冲突/iu.test(message);
  }

  async function mutate(action: (context: MutationContext) => Promise<void>) {
    if (busy || readOnly) return;
    const targetProjectId = project.projectId;
    const lifecycleSnapshot = lifecycle;
    if (!targetProjectId || !lifecycleSnapshot || persistenceMode !== "gateway") {
      error = "项目网关尚未就绪，无法执行该操作。";
      return;
    }

    const context: MutationContext = {
      projectId: targetProjectId,
      lifecycleSnapshot,
      loadGeneration,
      mutationToken: ++mutationSequence
    };
    activeMutationToken = context.mutationToken;
    busy = true;
    error = "";
    try {
      await action(context);
    } catch (cause) {
      if (!mutationIsCurrent(context)) return;
      const message = cause instanceof Error ? cause.message : String(cause);
      error = message;
      if (isLifecycleConflict(message)) {
        const generation = ++loadGeneration;
        persistenceMode = "loading";
        await loadLifecycle(context.projectId, generation);
      }
    } finally {
      if (activeMutationToken === context.mutationToken && project.projectId === context.projectId) {
        activeMutationToken = null;
        busy = false;
      }
    }
  }

  function saveGovernance() {
    void mutate(async (context) => {
      const governance: ProjectGovernance = {
        approvalPolicy: {
          standardApprovals: Math.max(1, Math.min(5, Number(standardApprovals) || 1)),
          productionApprovals: Math.max(2, Math.min(5, Number(productionApprovals) || 2))
        },
        artifactRetention: {
          maxArtifacts: Math.max(1, Math.min(50, Number(maxArtifacts) || 50)),
          maxAgeDays: Math.max(1, Math.min(3650, Number(maxAgeDays) || 180))
        },
        notificationRoutes: {
          approvalRequested: notifyApprovalRequested,
          releaseCompleted: notifyReleaseCompleted,
          rollbackCompleted: notifyRollbackCompleted,
          deploymentFailed: notifyDeploymentFailed
        }
      };
      const nextLifecycle = await api.saveProjectGovernance(
        context.projectId,
        governance,
        context.lifecycleSnapshot.revision
      );
      applyMutationLifecycle(context, nextLifecycle);
    });
  }

  async function storeRelease(
    context: MutationContext,
    nextArtifacts: ProjectArtifact[],
    nextReleases: ProjectRelease[]
  ) {
    const nextLifecycle = await api.saveProjectRelease(
      context.projectId,
      nextArtifacts.slice(0, 50),
      nextReleases.slice(0, 30),
      context.lifecycleSnapshot.revision
    );
    applyMutationLifecycle(context, nextLifecycle);
  }

  async function storeEnvironments(context: MutationContext, nextEnvironments: ProjectEnvironment[]) {
    const nextLifecycle = await api.saveProjectOperations(
      context.projectId,
      nextEnvironments.slice(0, 20),
      context.lifecycleSnapshot.revision
    );
    applyMutationLifecycle(context, nextLifecycle);
  }

  function formatTime(value: number | null) {
    return value
      ? new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(value)
      : "—";
  }

  function formatBytes(value: number | null | undefined) {
    if (value == null) return "大小未知";
    if (value < 1024) return `${value} B`;
    if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }

  function releaseEnvironment(release: ProjectRelease) {
    return environments.find((item) => item.id === release.targetEnvironmentId) ?? null;
  }

  function requiredApprovals(release: ProjectRelease) {
    return releaseEnvironment(release)?.kind === "production"
      ? lifecycle?.governance.approvalPolicy.productionApprovals ?? 2
      : lifecycle?.governance.approvalPolicy.standardApprovals ?? 1;
  }

  function selectArtifactFile(event: Event) {
    artifactFile = (event.currentTarget as HTMLInputElement).files?.[0] ?? null;
  }

  function createArtifact() {
    void mutate(async (context) => {
      const version = artifactVersion.trim();
      const selectedFile = artifactFile;
      if (!version || !selectedFile) throw new Error("请选择制品文件并填写版本。");
      if (persistenceMode !== "gateway") throw new Error("项目网关不可用，无法创建可信制品。");
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceCommit = context.lifecycleSnapshot.validation.runs.find(
        (run) => run.status === "passed"
      )?.commit ?? null;
      const artifact: ProjectArtifact = (
        await api.uploadProjectArtifact(
          context.projectId,
          version,
          sourceCommit,
          selectedFile
        )
      ).artifact;
      await storeRelease(
        context,
        [artifact, ...releaseSnapshot.artifacts],
        releaseSnapshot.releases
      );
      if (mutationIsCurrent(context)) {
        artifactVersion = "";
        artifactFile = null;
      }
    });
  }

  function verifyArtifact(artifact: ProjectArtifact) {
    void mutate(async (context) => {
      if (persistenceMode !== "gateway") throw new Error("安装新版项目网关后才能执行服务端签名验证。");
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceArtifact = releaseSnapshot.artifacts.find((item) => item.id === artifact.id);
      if (!sourceArtifact) throw new Error("该制品已不属于当前项目，请刷新后重试。");
      const verified = (await api.verifyProjectArtifact(context.projectId, sourceArtifact.id)).artifact;
      await storeRelease(
        context,
        releaseSnapshot.artifacts.map((item) => item.id === sourceArtifact.id ? verified : item),
        releaseSnapshot.releases
      );
    });
  }

  function downloadArtifact(artifact: ProjectArtifact) {
    void mutate(async (context) => {
      if (persistenceMode !== "gateway") throw new Error("本机暂存制品没有可下载的网关文件。");
      const sourceArtifact = context.lifecycleSnapshot.release.artifacts.find(
        (item) => item.id === artifact.id
      );
      if (!sourceArtifact) throw new Error("该制品已不属于当前项目，请刷新后重试。");
      const downloaded = await api.downloadProjectArtifact(context.projectId, sourceArtifact.id);
      if (!mutationIsCurrent(context)) return;
      const url = URL.createObjectURL(downloaded.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = downloaded.filename ?? sourceArtifact.name;
      anchor.click();
      URL.revokeObjectURL(url);
    });
  }

  function createRelease(artifact: ProjectArtifact) {
    void mutate(async (context) => {
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceArtifact = releaseSnapshot.artifacts.find((item) => item.id === artifact.id);
      if (!sourceArtifact) throw new Error("该制品已不属于当前项目，请刷新后重试。");
      const targetEnvironment = context.lifecycleSnapshot.operations.environments.find(
        (environment) => environment.id === releaseTargetEnvironmentId
      );
      if (!targetEnvironment) throw new Error("请选择有效的目标环境后再创建发布申请。");
      const release: ProjectRelease = {
        id: crypto.randomUUID(), version: sourceArtifact.version, artifactIds: [sourceArtifact.id],
        status: "awaitingApproval", targetEnvironmentId: targetEnvironment.id,
        approvals: [], createdAt: Date.now(), releasedAt: null, rollbackOf: null
      };
      await storeRelease(context, releaseSnapshot.artifacts, [release, ...releaseSnapshot.releases]);
    });
  }

  function approveRelease(release: ProjectRelease) {
    void mutate(async (context) => {
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceRelease = releaseSnapshot.releases.find((item) => item.id === release.id);
      if (!sourceRelease) throw new Error("该发布申请已变更，请刷新后重试。");
      const next = {
        ...sourceRelease,
        status: "approved" as const,
        approvals: [...sourceRelease.approvals, { profileId: "", role: "", approvedAt: Date.now() }]
      };
      await storeRelease(
        context,
        releaseSnapshot.artifacts,
        releaseSnapshot.releases.map((item) => item.id === sourceRelease.id ? next : item)
      );
    });
  }

  function markReleased(release: ProjectRelease) {
    void mutate(async (context) => {
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceRelease = releaseSnapshot.releases.find((item) => item.id === release.id);
      if (!sourceRelease) throw new Error("该发布申请已变更，请刷新后重试。");
      if (sourceRelease.status !== "approved") throw new Error("发布必须先通过审批。");
      const targetEnvironment = context.lifecycleSnapshot.operations.environments.find(
        (item) => item.id === sourceRelease.targetEnvironmentId
      );
      const approvalPolicy = context.lifecycleSnapshot.governance.approvalPolicy;
      const neededApprovals = targetEnvironment?.kind === "production"
        ? approvalPolicy.productionApprovals
        : approvalPolicy.standardApprovals;
      if (sourceRelease.approvals.length < neededApprovals) {
        throw new Error("生产发布需要两名不同操作者审批，且至少一名为所有者。");
      }
      if (targetEnvironment?.kind === "production"
        && !sourceRelease.artifactIds.every((artifactId) => releaseSnapshot.artifacts.some((item) => item.id === artifactId && item.signatureVerified))) {
        throw new Error("生产发布只允许使用通过服务端签名验证的制品。");
      }
      const next = { ...sourceRelease, status: "released" as const, releasedAt: Date.now() };
      await storeRelease(
        context,
        releaseSnapshot.artifacts,
        releaseSnapshot.releases.map((item) => item.id === sourceRelease.id ? next : item)
      );
    });
  }

  function rollbackRelease(release: ProjectRelease) {
    void mutate(async (context) => {
      const releaseSnapshot = context.lifecycleSnapshot.release;
      const sourceRelease = releaseSnapshot.releases.find((item) => item.id === release.id);
      if (!sourceRelease) throw new Error("该发布记录已变更，请刷新后重试。");
      if (sourceRelease.status !== "released") throw new Error("只有已发布版本可以回滚。");
      const next = { ...sourceRelease, status: "rolledBack" as const };
      await storeRelease(
        context,
        releaseSnapshot.artifacts,
        releaseSnapshot.releases.map((item) => item.id === sourceRelease.id ? next : item)
      );
    });
  }

  function validateGitHubAdapter(repository: string, workflow: string, refName: string) {
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(repository)) throw new Error("GitHub 仓库必须使用 owner/repository 格式。");
    if (!/^[A-Za-z0-9_./-]+$/u.test(workflow) || !/^[A-Za-z0-9_./-]+$/u.test(refName)) {
      throw new Error("工作流和分支只能包含字母、数字、点、斜杠、横线和下划线。");
    }
  }

  function addEnvironment() {
    void mutate(async (context) => {
      const name = environmentName.trim();
      const url = environmentUrl.trim();
      const adapter = environmentAdapter;
      const localDeployCommand = deployCommand.trim();
      const repository = githubRepository.trim();
      const workflow = githubWorkflow.trim();
      const refName = githubRef.trim();
      const environmentHealthCommand = healthCommand.trim();
      if (!name) throw new Error("请填写环境名称。");
      if (adapter === "githubActions") validateGitHubAdapter(repository, workflow, refName);
      const environment: ProjectEnvironment = {
        id: crypto.randomUUID(), name, kind: environmentKind,
        url: url || null,
        deployCommand: adapter === "localCommand" ? localDeployCommand || null : null,
        adapter,
        githubRepository: adapter === "githubActions" ? repository : null,
        githubWorkflow: adapter === "githubActions" ? workflow : null,
        githubRef: adapter === "githubActions" ? refName : null,
        healthCommand: environmentHealthCommand || null,
        health: "unknown", lastCheckedAt: null, lastHealthOutput: null
      };
      await storeEnvironments(
        context,
        [environment, ...context.lifecycleSnapshot.operations.environments]
      );
      if (mutationIsCurrent(context)) {
        environmentName = ""; environmentUrl = ""; deployCommand = "";
        githubRepository = ""; githubWorkflow = ""; githubRef = "main"; healthCommand = "";
      }
    });
  }

  function checkHealth(environment: ProjectEnvironment) {
    void mutate(async (context) => {
      const sourceEnvironment = context.lifecycleSnapshot.operations.environments.find(
        (item) => item.id === environment.id
      );
      if (!sourceEnvironment) throw new Error("该环境已不属于当前项目，请刷新后重试。");
      if (!sourceEnvironment.healthCommand) throw new Error("该环境尚未配置健康检查命令。");
      const nextLifecycle = await api.checkProjectEnvironment(
        context.projectId,
        sourceEnvironment.id,
        context.lifecycleSnapshot.revision
      );
      applyMutationLifecycle(context, nextLifecycle);
    });
  }

  function deployRelease(environment: ProjectEnvironment) {
    void mutate(async (context) => {
      const sourceEnvironment = context.lifecycleSnapshot.operations.environments.find(
        (item) => item.id === environment.id
      );
      if (!sourceEnvironment) throw new Error("该环境已不属于当前项目，请刷新后重试。");
      const release = context.lifecycleSnapshot.release.releases.find(
        (item) => item.status === "released" && item.targetEnvironmentId === sourceEnvironment.id
      );
      if (!release) throw new Error("请先完成一个面向该环境的版本审批与发布。");
      const nextLifecycle = await api.runProjectDeployment(
        context.projectId,
        release.id,
        sourceEnvironment.id,
        context.lifecycleSnapshot.revision
      );
      applyMutationLifecycle(context, nextLifecycle);
    });
  }

  $effect(() => {
    const targetProjectId = project.projectId;
    const generation = ++loadGeneration;
    activeMutationToken = null;
    lifecycle = null;
    persistenceMode = "loading";
    busy = false;
    error = "";
    releaseTargetEnvironmentId = "";
    if (!targetProjectId) {
      persistenceMode = "unavailable";
      error = "项目尚未完成 Project Registry V2 注册，无法读取生命周期数据。";
      return;
    }
    void loadLifecycle(targetProjectId, generation);
  });
</script>

<section class="h-full overflow-y-auto bg-[#f7f8fb]" data-testid={`project-${surface}-workspace`}>
  <div class="mx-auto w-full max-w-6xl px-6 py-8 lg:px-10 lg:py-10">
    <header class="flex flex-col gap-5 border-b border-slate-200 pb-7 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <p class="text-[10px] font-bold tracking-[0.22em] text-violet-600">{surface === "release" ? "版本治理" : "运行维护"}</p>
        <h1 class="mt-2 text-2xl font-bold text-slate-950">{surface === "release" ? "发布与版本治理" : "环境与运行维护"}</h1>
        <p class="mt-2 max-w-2xl text-sm leading-6 text-slate-500">{surface === "release" ? "上传真实制品、验证签名、执行分级审批，并将可信版本交付到目标环境。" : "配置本地命令或 GitHub Actions 部署适配器，受控执行部署与健康检查。"}</p>
        <p class="mt-2 text-[11px] font-semibold text-slate-400">{project.name} · {persistenceMode === "gateway" ? "项目网关持久化与审计" : persistenceMode === "unavailable" ? "项目网关不可用" : "正在读取项目状态"}</p>
      </div>
      <button class="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700" onclick={onConfigure} type="button"><ServerCog size={16} />项目设置</button>
    </header>

    {#if error}<div class="mt-5 flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"><AlertCircle size={16} />{error}</div>{/if}
    {#if surface === "release"}
      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">可信基线</p><p class="mt-4 text-lg font-bold text-slate-950">{latestPassedValidation?.commit?.slice(0, 10) ?? "等待验证"}</p><p class="mt-2 text-xs text-slate-400">最近通过验证的 Git 提交</p></article>
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">已签名制品</p><p class="mt-4 text-lg font-bold text-slate-950">{artifacts.filter((item) => item.signatureVerified).length} / {artifacts.length}</p><p class="mt-2 text-xs text-slate-400">服务端摘要与签名验证</p></article>
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">当前版本</p><p class="mt-4 text-lg font-bold text-slate-950">{latestRelease?.version ?? "尚未创建"}</p><p class="mt-2 text-xs text-slate-400">{latestRelease?.status ?? "等待制品"}</p></article>
      </div>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <div class="flex flex-wrap items-start gap-4">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2"><ShieldCheck class="text-violet-600" size={18} /><h2 class="text-sm font-bold text-slate-900">企业发布策略</h2></div>
            <p class="mt-2 text-xs leading-5 text-slate-500">项目所有者可配置审批人数、制品保留窗口和企业通知路由。生产发布始终要求所有者参与，并且只能使用网关验证过的签名制品。</p>
          </div>
          <button class="inline-flex items-center gap-2 rounded-xl bg-slate-950 px-4 py-2.5 text-xs font-bold text-white disabled:opacity-50" disabled={busy || readOnly} onclick={saveGovernance} type="button"><Save size={14} />保存治理策略</button>
        </div>
        <div class="mt-4 grid gap-4 lg:grid-cols-3">
          <div class="rounded-xl bg-slate-50 p-4">
            <p class="text-xs font-bold text-slate-800">审批门禁</p>
            <div class="mt-3 grid grid-cols-2 gap-3">
              <label class="text-[11px] text-slate-500">普通环境<input class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" type="number" min="1" max="5" bind:value={standardApprovals} /></label>
              <label class="text-[11px] text-slate-500">生产环境<input class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" type="number" min="2" max="5" bind:value={productionApprovals} /></label>
            </div>
            <p class="mt-2 text-[10px] leading-4 text-slate-400">生产审批至少 2 人，且必须包含项目所有者。</p>
          </div>
          <div class="rounded-xl bg-slate-50 p-4">
            <p class="text-xs font-bold text-slate-800">制品保留</p>
            <div class="mt-3 grid grid-cols-2 gap-3">
              <label class="text-[11px] text-slate-500">活跃制品上限<input class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" type="number" min="1" max="50" bind:value={maxArtifacts} /></label>
              <label class="text-[11px] text-slate-500">保留天数<input class="mt-1 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm" type="number" min="1" max="3650" bind:value={maxAgeDays} /></label>
            </div>
            <p class="mt-2 text-[10px] leading-4 text-slate-400">{lifecycle?.retentionStatus.eligibleForArchive.length ?? 0} 个制品达到归档条件；本阶段不自动删除，已发布制品始终受保护。</p>
          </div>
          <div class="rounded-xl bg-slate-50 p-4">
            <p class="text-xs font-bold text-slate-800">企业通知路由</p>
            <div class="mt-3 grid grid-cols-2 gap-2 text-[11px] text-slate-600">
              <label class="flex items-center gap-2"><input type="checkbox" bind:checked={notifyApprovalRequested} />等待审批</label>
              <label class="flex items-center gap-2"><input type="checkbox" bind:checked={notifyReleaseCompleted} />发布完成</label>
              <label class="flex items-center gap-2"><input type="checkbox" bind:checked={notifyRollbackCompleted} />版本回滚</label>
              <label class="flex items-center gap-2"><input type="checkbox" bind:checked={notifyDeploymentFailed} />部署失败</label>
            </div>
            <p class="mt-3 text-[10px] leading-4 text-slate-400">事件进入站内通知，并按系统设置投递到 Slack 或企业 Webhook。</p>
          </div>
        </div>
      </section>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <div class="flex items-center gap-2"><Upload class="text-violet-600" size={18} /><h2 class="text-sm font-bold text-slate-900">上传发布制品</h2></div>
        <p class="mt-2 text-xs leading-5 text-slate-500">文件由项目网关存储，SHA-256 与 HMAC 签名由服务端生成；每次下载前都会重新验证。</p>
        <div class="mt-4 grid gap-3 md:grid-cols-[1fr_10rem_auto]">
          <label class="flex min-h-11 items-center rounded-xl border border-dashed border-slate-300 px-3 text-sm text-slate-600"><input class="w-full text-xs" type="file" onchange={selectArtifactFile} /></label>
          <input class="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" bind:value={artifactVersion} placeholder="版本 1.2.0" />
          <button class="inline-flex items-center justify-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50" disabled={busy || readOnly} onclick={createArtifact} type="button"><Plus size={15} />上传并签名</button>
        </div>
      </section>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <div class="flex flex-wrap items-center gap-3"><h2 class="min-w-0 flex-1 text-sm font-bold text-slate-900">制品、目标环境与发布门禁</h2><select class="rounded-xl border border-slate-200 px-3 py-2 text-xs" bind:value={releaseTargetEnvironmentId}><option value="">请选择目标环境</option>{#each environments as environment (environment.id)}<option value={environment.id}>{environment.name} · {environment.kind === "production" ? "生产" : environment.kind}</option>{/each}</select></div>
        <div class="mt-4 space-y-3">
          {#if artifacts.length === 0}<div class="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">尚无制品。先完成项目验证，再上传发布文件。</div>{/if}
          {#each artifacts as artifact (artifact.id)}
            {@const release = releases.find((item) => item.artifactIds.includes(artifact.id))}
            <article class="rounded-2xl border border-slate-200 p-4">
              <div class="flex flex-wrap items-center gap-3">
                {#if artifact.signatureVerified}<FileCheck2 class="text-emerald-500" size={18} />{:else}<PackageCheck class="text-amber-500" size={18} />{/if}
                <div class="min-w-0 flex-1"><p class="font-bold text-slate-900">{artifact.name} · {artifact.version}</p><p class="mt-1 truncate font-mono text-[11px] text-slate-400">{formatBytes(artifact.size)} · 提交 {artifact.sourceCommit?.slice(0, 12) ?? "未绑定"} · SHA-256 {artifact.sha256?.slice(0, 20) ?? "未生成"}</p><p class="mt-1 text-[11px] font-semibold {artifact.signatureVerified ? 'text-emerald-600' : 'text-amber-600'}">{artifact.signatureVerified ? "签名已验证" : "尚未获得网关签名"}{artifact.signatureAlgorithm ? ` · ${artifact.signatureAlgorithm}` : ""}</p></div>
                <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || readOnly || persistenceMode !== "gateway"} onclick={() => verifyArtifact(artifact)} type="button"><ShieldCheck class="mr-1 inline" size={13} />验证</button>
                <button class="rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || readOnly || persistenceMode !== "gateway"} onclick={() => downloadArtifact(artifact)} type="button"><Download class="mr-1 inline" size={13} />下载</button>
                {#if !release}<button class="rounded-xl border border-violet-200 px-3 py-2 text-xs font-bold text-violet-700 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || readOnly || !selectedReleaseEnvironment} onclick={() => createRelease(artifact)} type="button">创建发布申请</button>{/if}
              </div>
              {#if release}
                {@const needed = requiredApprovals(release)}
                <div class="mt-3 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3 text-[11px] text-slate-500"><span>状态：{release.status}</span><span>目标：{releaseEnvironment(release)?.name ?? "未指定"}</span><span>审批：{release.approvals.length} / {needed}</span><span>发布时间：{formatTime(release.releasedAt)}</span><span class="min-w-0 flex-1"></span>{#if release.status === "awaitingApproval" || (release.status === "approved" && release.approvals.length < needed)}<button class="rounded-lg bg-amber-500 px-3 py-1.5 font-bold text-white" disabled={busy || readOnly} onclick={() => approveRelease(release)} type="button">{release.approvals.length === 0 ? "人工审批" : "添加独立复核"}</button>{:else if release.status === "approved"}<button class="rounded-lg bg-violet-600 px-3 py-1.5 font-bold text-white" disabled={busy || readOnly} onclick={() => markReleased(release)} type="button"><Rocket class="mr-1 inline" size={13} />确认发布</button>{:else if release.status === "released"}<button class="rounded-lg border border-red-200 px-3 py-1.5 font-bold text-red-600" disabled={busy || readOnly} onclick={() => rollbackRelease(release)} type="button"><RotateCcw class="mr-1 inline" size={13} />回滚版本</button>{:else}<span class="rounded-full bg-slate-100 px-3 py-1 font-bold text-slate-500">已回滚</span>{/if}</div>
                {#if needed === 2 && release.approvals.length < 2}<p class="mt-2 text-xs text-amber-700">生产门禁：需要两名不同操作者审批，且至少一名为项目所有者。请切换到另一审批账号完成复核。</p>{/if}
              {/if}
            </article>
          {/each}
        </div>
      </section>
    {:else}
      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">运行环境</p><p class="mt-4 text-lg font-bold text-slate-950">{environments.length} 个</p><p class="mt-2 text-xs text-slate-400">开发、测试、预发和生产</p></article>
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">健康环境</p><p class="mt-4 text-lg font-bold text-slate-950">{environments.filter((item) => item.health === "healthy").length} 个</p><p class="mt-2 text-xs text-slate-400">来自真实命令探测结果</p></article>
        <article class="rounded-2xl border border-slate-200 bg-white p-5"><p class="text-xs font-bold text-slate-500">部署记录</p><p class="mt-4 text-lg font-bold text-slate-950">{deployments.length} 次</p><p class="mt-2 text-xs text-slate-400">操作者、版本、结果与日志</p></article>
      </div>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <div class="flex items-center gap-2"><ServerCog class="text-violet-600" size={18} /><h2 class="text-sm font-bold text-slate-900">接入运行环境</h2></div>
        <div class="mt-4 grid gap-3 md:grid-cols-2">
          <input class="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" bind:value={environmentName} placeholder="环境名称" />
          <select class="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" bind:value={environmentKind}><option value="development">开发环境</option><option value="test">测试环境</option><option value="staging">预发环境</option><option value="production">生产环境</option></select>
          <input class="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" bind:value={environmentUrl} placeholder="访问地址（可选）" />
          <select class="rounded-xl border border-slate-200 px-3 py-2.5 text-sm" bind:value={environmentAdapter}><option value="localCommand">项目目录命令</option><option value="githubActions">GitHub Actions 工作流</option></select>
          {#if environmentAdapter === "githubActions"}
            <input class="rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-xs" bind:value={githubRepository} placeholder="仓库 owner/repository" />
            <input class="rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-xs" bind:value={githubWorkflow} placeholder="工作流 deploy.yml" />
            <input class="rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-xs" bind:value={githubRef} placeholder="分支 main" />
          {:else}
            <input class="rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-xs" bind:value={deployCommand} placeholder="部署命令（仅在明确点击部署后执行）" />
          {/if}
          <input class="rounded-xl border border-slate-200 px-3 py-2.5 font-mono text-xs" bind:value={healthCommand} placeholder="健康检查命令，例如 curl ..." />
        </div>
        <button class="mt-3 inline-flex items-center gap-2 rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-bold text-white disabled:opacity-50" disabled={busy || readOnly || persistenceMode !== "gateway"} onclick={addEnvironment} type="button"><Save size={15} />保存环境</button>
      </section>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <h2 class="text-sm font-bold text-slate-900">环境运行控制</h2>
        <div class="mt-4 space-y-3">
          {#if environments.length === 0}<div class="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">尚未接入运行环境。</div>{/if}
          {#each environments as environment (environment.id)}
            <article class="rounded-2xl border border-slate-200 p-4">
              <div class="flex flex-wrap items-center gap-3">
                {#if environment.health === "healthy"}<CheckCircle2 class="text-emerald-500" size={18} />{:else if environment.health === "unhealthy"}<XCircle class="text-red-500" size={18} />{:else}<CircleDashed class="text-slate-400" size={18} />{/if}
                <div class="min-w-0 flex-1"><p class="font-bold text-slate-900">{environment.name}</p><p class="mt-1 text-[11px] text-slate-400">{environment.kind} · {environment.adapter === "githubActions" ? `GitHub Actions · ${environment.githubRepository}` : "项目目录命令"} · 最近探测 {formatTime(environment.lastCheckedAt)}</p></div>
                <button class="inline-flex items-center gap-1 rounded-xl border border-slate-200 px-3 py-2 text-xs font-bold text-slate-700 disabled:opacity-50" disabled={busy || readOnly || persistenceMode !== "gateway" || !environment.healthCommand} onclick={() => checkHealth(environment)} type="button"><HeartPulse size={14} />健康检查</button>
                <button class="inline-flex items-center gap-1 rounded-xl bg-violet-600 px-3 py-2 text-xs font-bold text-white disabled:opacity-50" disabled={busy || readOnly || persistenceMode !== "gateway" || (!environment.deployCommand && environment.adapter !== "githubActions")} onclick={() => deployRelease(environment)} type="button">{#if environment.adapter === "githubActions"}<ExternalLink size={14} />{:else}<Play size={14} />{/if}部署已发布版本</button>
              </div>
              {#if environment.url}<a class="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-violet-600" href={environment.url} rel="noreferrer" target="_blank">打开运行地址<ExternalLink size={12} /></a>{/if}
              {#if environment.lastHealthCheck}<p class="mt-2 text-[11px] text-slate-400">网关证据 · {environment.lastHealthCheck.operator?.profileId ?? "未知操作者"} · 摘要 {environment.lastHealthCheck.evidenceDigest?.slice(0, 16) ?? "处理中"}</p>{/if}
              {#if environment.lastHealthOutput}<pre class="mt-3 max-h-36 overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-3 font-mono text-[11px] text-slate-200">{environment.lastHealthOutput}</pre>{/if}
            </article>
          {/each}
        </div>
      </section>

      <section class="mt-6 rounded-2xl border border-slate-200 bg-white p-5">
        <div class="flex items-center gap-2"><History class="text-violet-500" size={17} /><h2 class="text-sm font-bold text-slate-900">部署历史</h2></div>
        <div class="mt-4 space-y-2">
          {#if deployments.length === 0}<p class="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">暂无部署记录。</p>{/if}
          {#each deployments as deployment (deployment.id)}
            <div class="rounded-xl border border-slate-200 px-4 py-3"><div class="flex items-center gap-3"><TerminalSquare class="text-slate-400" size={16} /><p class="min-w-0 flex-1 text-sm font-bold text-slate-800">{releases.find((item) => item.id === deployment.releaseId)?.version ?? deployment.releaseId} → {environments.find((item) => item.id === deployment.environmentId)?.name ?? deployment.environmentId}</p><span class="text-xs font-bold {deployment.status === 'succeeded' ? 'text-emerald-600' : deployment.status === 'failed' ? 'text-red-600' : 'text-amber-600'}">{deployment.status}</span></div><p class="mt-2 text-[11px] text-slate-400">{formatTime(deployment.startedAt)} · 操作者 {deployment.operator?.profileId ?? "等待网关记录"} · 退出码 {deployment.exitCode ?? "—"} · 摘要 {deployment.evidenceDigest?.slice(0, 16) ?? "处理中"}</p>{#if deployment.logs}<pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 font-mono text-[11px] text-slate-200">{deployment.logs}</pre>{/if}</div>
          {/each}
        </div>
      </section>
    {/if}
  </div>
</section>
