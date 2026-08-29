import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

const port = Number(process.env.CODEX_WEBUI_E2E_PORT ?? 44173);
const basePath = process.env.CODEX_WEBUI_E2E_BASE_PATH ?? "/e2e/base";
const password = process.env.CODEX_WEBUI_E2E_PASSWORD ?? "test";
const baseURL = `http://127.0.0.1:${port}${basePath}`;
const fakeCodexBin =
  process.env.CODEX_WEBUI_E2E_FAKE_CODEX_BIN ??
  path.join(process.cwd(), "backend", "target", "debug", `fake_codex_app_server${process.platform === "win32" ? ".exe" : ""}`);
const gatewayBin =
  process.env.CODEX_WEBUI_E2E_GATEWAY_BIN ??
  path.join(process.cwd(), "backend", "target", "release", `backend${process.platform === "win32" ? ".exe" : ""}`);
const gatewayDataDir =
  process.env.CODEX_WEBUI_E2E_DATA_DIR ??
  path.join(process.env.RUNNER_TEMP ?? os.tmpdir(), `forgeos-e2e-data-${port}`);

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  retries: 0,
  timeout: 90_000,
  expect: {
    timeout: 15_000
  },
  use: {
    baseURL,
    browserName: "chromium",
    trace: "retain-on-failure"
  },
  webServer: {
    command: `"${gatewayBin}"`,
    cwd: ".",
    timeout: 180_000,
    reuseExistingServer: false,
    url: `${baseURL}/`,
    env: {
      ...process.env,
      HOST: "127.0.0.1",
      PORT: String(port),
      CODEX_WEBUI_BASE_PATH: basePath,
      CODEX_WEBUI_ALLOWED_ROOTS: process.cwd(),
      CODEX_WEBUI_CODEX_BIN: fakeCodexBin,
      CODEX_WEBUI_DATA_DIR: gatewayDataDir,
      CODEX_WEBUI_MAX_APP_SERVERS: "1",
      CODEX_WEBUI_PASSWORD: password,
      CODEX_WEBUI_SESSION_SECRET: "codex-webui-e2e-session-secret-000000",
      CODEX_WEBUI_SERVER_THREADS: "1",
      CODEX_WEBUI_BLOCKING_THREADS: "4",
      CODEX_WEBUI_SERVER_THREAD_STACK_BYTES: "2097152",
      RUST_LOG: process.env.RUST_LOG ?? "info"
    }
  }
});
