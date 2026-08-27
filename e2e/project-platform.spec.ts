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
  await login(page);
  const projectName = `Enterprise Pilot ${Date.now()}`;
  const created = await wsRequest(page, "sessionFolders/upsert", {
    name: projectName,
    pinned: true,
    rootPath: process.cwd(),
    repoPath: process.cwd(),
    markOpened: true
  });
  expect(created.ok, created.error).toBeTruthy();

  try {
    await page.reload();
    const card = page.getByTestId("project-folder-card").filter({ hasText: projectName });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "发布" }).click();
    await expect(page.getByTestId("project-navigation")).toBeVisible();
    await expect(page.getByTestId("project-release-workspace")).toBeVisible();

    await page.getByRole("button", { name: "运维" }).last().click();
    await expect(page.getByTestId("project-operations-workspace")).toBeVisible();

    await page.getByRole("button", { name: "验证" }).last().click();
    await expect(page.getByTestId("project-validation-workspace")).toBeVisible();
    await page.getByRole("button", { name: "配置流程" }).click();
    await page.locator("#validation-build").fill("node -e \"console.log('forgeos-validation-e2e')\"");
    await page.getByRole("button", { name: "保存配置" }).click();
    await page.getByTestId("validation-run").click();
    await expect(page.getByTestId("validation-history").getByText("验证通过").first()).toBeVisible({ timeout: 30_000 });

    await page.getByRole("button", { name: "AI 开发" }).click();
    await expect(page.getByTestId("composer-input")).toBeVisible();

    await page.getByRole("button", { name: "项目中心" }).click();
    await expect(page.getByTestId("enterprise-project-portal")).toBeVisible();
  } finally {
    const removed = await wsRequest(page, "sessionFolders/delete", {
      name: projectName,
      removeFromSessions: true
    });
    expect(removed.ok, removed.error).toBeTruthy();
  }
});
