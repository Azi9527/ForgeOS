import { expect, test } from "@playwright/test";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, rmdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

const DEV_BYPASS_COOKIE = {
  name: "dev_bypass_waf",
  value: "seorii_bypass_token_is_this"
};

type WsResponse<T> = {
  kind: "response";
  id: string;
  ok: boolean;
  result?: T;
  error?: string;
};

test.beforeEach(async ({ baseURL, context }) => {
  if (!baseURL) {
    throw new Error("Expected Playwright baseURL to be configured.");
  }
  await context.addCookies([{ ...DEV_BYPASS_COOKIE, url: baseURL }]);
});

async function wsRequest<T>(
  page: import("@playwright/test").Page,
  method: string,
  params: Record<string, unknown>,
  timeoutMs = 15_000
) {
  return page.evaluate(
    ({ method, params, timeoutMs }) =>
      new Promise<WsResponse<T>>((resolve, reject) => {
        const url = new URL(window.location.href);
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        url.pathname = `${url.pathname.replace(/\/$/u, "")}/ws`;
        url.search = "";
        const id = `project-platform-${Date.now()}`;
        const socket = new WebSocket(url.toString());
        const timeout = window.setTimeout(() => reject(new Error(`Timed out waiting for ${method}`)), timeoutMs);
        socket.addEventListener("open", () => socket.send(JSON.stringify({ kind: "request", id, method, params })));
        socket.addEventListener("message", (event) => {
          if (typeof event.data !== "string") return;
          const payload = JSON.parse(event.data) as WsResponse<T>;
          if (payload.kind !== "response" || payload.id !== id) return;
          window.clearTimeout(timeout);
          socket.close();
          resolve(payload);
        });
        socket.addEventListener("error", () => {
          window.clearTimeout(timeout);
          reject(new Error(`WebSocket ${method} request failed.`));
        });
      }),
    { method, params, timeoutMs }
  );
}

function shellQuote(value: string) {
  if (process.platform === "win32") {
    return `'${value.replaceAll("'", "''")}'`;
  }
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("login-password").fill(process.env.CODEX_WEBUI_E2E_PASSWORD ?? "test");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("enterprise-project-portal")).toBeVisible();
}

test("opens a project folder into release and operations workspaces", async ({ page }) => {
  test.setTimeout(180_000);
  await login(page);
  const projectName = `Enterprise Pilot ${Date.now()}`;
  const projectContainer = mkdtempSync(join(process.cwd(), ".forgeos-e2e-"));
  const projectRoot = join(projectContainer, projectName);
  const created = await wsRequest<{
    project: { projectId: string; name: string };
  }>(page, "project/create", {
    name: projectName,
    rootPath: projectRoot,
    repositoryRoot: process.cwd()
  });
  expect(created.ok, created.error).toBeTruthy();
  const projectId = created.result?.project.projectId;
  expect(projectId).toMatch(/^prj_/u);

  try {
    await page.reload();
    await page
      .getByTestId("enterprise-rail")
      .getByRole("button", { name: /项目中心/u })
      .click();
    const card = page.getByTestId("project-folder-card").filter({ hasText: projectName });
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-project-id", projectId ?? "");
    await card.getByRole("button", { name: "发布", exact: true }).click();
    const projectNavigation = page.getByTestId("project-navigation");
    await expect(projectNavigation).toBeVisible();
    await expect(page.getByTestId("project-release-workspace")).toBeVisible();

    await projectNavigation.getByRole("button", { name: "环境", exact: true }).click({ timeout: 15_000 });
    await expect(page.getByTestId("project-operations-workspace")).toBeVisible();

    await projectNavigation.getByRole("button", { name: "验证", exact: true }).click({ timeout: 15_000 });
    await expect(page.getByTestId("project-validation-workspace")).toBeVisible();
    await page.getByRole("button", { name: "配置流程", exact: true }).click({ timeout: 15_000 });
    await page.locator("#validation-build").fill("node -e \"console.log('forgeos-validation-e2e')\"");
    await page.getByRole("button", { name: "保存配置", exact: true }).click({ timeout: 15_000 });
    await page.getByTestId("validation-run").click({ timeout: 15_000 });
    await expect(page.getByTestId("validation-history").getByText("验证通过").first()).toBeVisible({ timeout: 30_000 });

    await projectNavigation.getByRole("button", { name: "设置", exact: true }).click({ timeout: 15_000 });
    const migrationPanel = page.getByTestId("project-lifecycle-migration");
    await expect(migrationPanel).toBeVisible();
    await expect(migrationPanel).toContainText(projectId ?? "");
    await expect(migrationPanel).toContainText("已使用 projectId，无旧数据需要迁移");

    await projectNavigation.getByRole("button", { name: "AI 开发", exact: true }).click({ timeout: 15_000 });
    await expect(page.getByTestId("composer-input")).toBeVisible();

    await projectNavigation.getByRole("button", { name: "项目", exact: true }).click({ timeout: 15_000 });
    await expect(page.getByTestId("enterprise-project-portal")).toBeVisible();
  } finally {
    try {
      if (projectId) {
        const removed = await wsRequest(page, "project/archive", {
          projectId
        });
        expect(removed.ok, removed.error).toBeTruthy();
      }
    } finally {
      rmSync(projectContainer, { recursive: true, force: true });
    }
  }
});

test("runs the real ForgeOS repository build through gateway validation and records audit", async ({ page }) => {
  test.setTimeout(600_000);
  await login(page);

  const repositoryRoot = process.cwd();
  const manifestPath = join(repositoryRoot, ".forgeos", "project.json");
  const previousManifest = existsSync(manifestPath) ? readFileSync(manifestPath) : null;
  let projectId: string | undefined;
  let registeredForPilot = false;

  try {
    const created = await wsRequest<{
      created: boolean;
      project: { projectId: string; name: string };
    }>(page, "project/create", {
      name: "ForgeOS Real Repository Pilot",
      rootPath: repositoryRoot,
      repositoryRoot
    });
    expect(created.ok, created.error).toBeTruthy();
    projectId = created.result?.project.projectId;
    registeredForPilot = created.result?.created ?? false;
    expect(projectId).toMatch(/^prj_/u);

    const initial = await wsRequest<{ revision: number }>(page, "projectLifecycle/get", { projectId });
    expect(initial.ok, initial.error).toBeTruthy();
    const configured = await wsRequest<{ revision: number }>(page, "projectLifecycle/validation/save", {
      projectId,
      expectedRevision: initial.result?.revision,
      checks: [
        {
          id: "build",
          label: "ForgeOS 生产构建",
          command: `pnpm --dir ${shellQuote(repositoryRoot)} build`,
          required: true
        },
        {
          id: "test",
          label: "ForgeOS 前端回归",
          command: `pnpm --dir ${shellQuote(repositoryRoot)} test:frontend`,
          required: true
        }
      ]
    });
    expect(configured.ok, configured.error).toBeTruthy();

    const validated = await wsRequest<{
      validation: {
        runs: Array<{
          status: string;
          commit: string | null;
          evidenceDigest: string;
          checks: Array<{ status: string; exitCode: number | null }>;
          operator: { profileId: string; role: string };
        }>;
      };
    }>(page, "projectLifecycle/validation/run", {
      projectId,
      expectedRevision: configured.result?.revision
    }, 480_000);
    expect(validated.ok, validated.error).toBeTruthy();
    const run = validated.result?.validation.runs[0];
    expect(run?.status).toBe("passed");
    expect(run?.checks.every((check) => check.status === "passed" && check.exitCode === 0)).toBeTruthy();
    expect(run?.commit).toMatch(/^[a-f0-9]{40}$/u);
    expect(run?.evidenceDigest).toMatch(/^[a-f0-9]{64}$/u);
    expect(run?.operator.profileId).toBeTruthy();

    await expect.poll(async () => {
      const audit = await wsRequest<{
        entries: Array<{ method: string; target: string | null; ok: boolean }>;
      }>(page, "projectLifecycle/audit/list", { projectId, limit: 50 });
      return audit.ok && audit.result?.entries.some((entry) =>
        entry.method === "projectLifecycle/validation/run" && entry.target === projectId && entry.ok
      );
    }, { timeout: 20_000 }).toBe(true);
  } finally {
    try {
      if (projectId && registeredForPilot) {
        await wsRequest(page, "project/archive", { projectId });
      }
    } finally {
      if (previousManifest) {
        mkdirSync(dirname(manifestPath), { recursive: true });
        writeFileSync(manifestPath, previousManifest);
      } else {
        rmSync(manifestPath, { force: true });
        try {
          rmdirSync(dirname(manifestPath));
        } catch {
          // Preserve a non-empty project metadata directory created by another process.
        }
      }
    }
  }
});
