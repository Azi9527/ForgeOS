import { expect, test } from "@playwright/test";

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

async function wsRequest<T>(page: import("@playwright/test").Page, method: string, params: Record<string, unknown>) {
  return page.evaluate(
    ({ method, params }) =>
      new Promise<WsResponse<T>>((resolve, reject) => {
        const url = new URL(window.location.href);
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        url.pathname = `${url.pathname.replace(/\/$/u, "")}/ws`;
        url.search = "";
        const id = `project-platform-${Date.now()}`;
        const socket = new WebSocket(url.toString());
        const timeout = window.setTimeout(() => reject(new Error(`Timed out waiting for ${method}`)), 15_000);
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
    { method, params }
  );
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
  const created = await wsRequest<{
    project: { projectId: string; name: string };
  }>(page, "project/create", {
    name: projectName,
    rootPath: process.cwd(),
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
    const removed = await wsRequest(page, "project/archive", {
      projectId
    });
    expect(removed.ok, removed.error).toBeTruthy();
  }
});
