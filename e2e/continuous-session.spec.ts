import { expect, test } from "@playwright/test";

const DEV_BYPASS_COOKIE = {
  name: "dev_bypass_waf",
  value: "seorii_bypass_token_is_this"
};

test.beforeEach(async ({ baseURL, context }) => {
  if (!baseURL) {
    throw new Error("Expected Playwright baseURL to be configured.");
  }
  await context.addCookies([{ ...DEV_BYPASS_COOKIE, url: baseURL }]);
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page.getByTestId("login-password").fill(process.env.CODEX_WEBUI_E2E_PASSWORD ?? "test");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("workspace-shell")).toBeVisible();
  const appUrl = new URL(page.url());
  appUrl.search = "?sessionNew=1";
  await page.goto(appUrl.toString());
  await expect(page.getByTestId("composer-input")).toBeVisible();
}

test("keeps a background Codex conversation across disconnect and reload", async ({ context, page }) => {
  await login(page);

  const prompt = `continuous-background-${Date.now()}`;
  await page.getByTestId("composer-input").fill(prompt);
  await page.getByTestId("composer-submit").click();
  await expect(page).toHaveURL(/session=/u);
  await expect(page.getByText(prompt, { exact: false }).first()).toBeVisible();

  await context.setOffline(true);
  await expect(page.getByTestId("connection-snackbar")).toBeVisible();
  await context.setOffline(false);
  await expect(page.getByTestId("connection-snackbar")).toBeHidden({ timeout: 20_000 });

  const sessionUrl = page.url();
  await page.reload();
  await expect(page.getByTestId("workspace-shell")).toBeVisible();
  await expect(page).toHaveURL(sessionUrl);
  await expect(page.getByText(prompt, { exact: false }).first()).toBeVisible();
  await expect(page.getByTestId("composer-input")).toBeVisible();
});
