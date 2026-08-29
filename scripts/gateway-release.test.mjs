import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  installGatewayBundle,
  readGatewayReleaseState,
  restartGatewayWithReleaseRecovery,
  resolveInstalledGatewayRelease,
  rollbackGatewayRelease,
  waitForGatewayReadiness
} from "./gateway-release.mjs";

async function createBundle(root, version, contents) {
  const binary = path.join(root, "dist", "backend", "test-target", "backend");
  await fs.mkdir(path.dirname(binary), { recursive: true });
  await fs.writeFile(binary, contents);
  await fs.mkdir(path.join(root, "build", "static"), { recursive: true });
  await fs.writeFile(path.join(root, "build", "static", "index.html"), `<html>${version}</html>`);
  await fs.writeFile(
    path.join(root, "forgeos-gateway.json"),
    JSON.stringify({
      schemaVersion: 1,
      version,
      target: "test-target",
      binary: "dist/backend/test-target/backend",
      staticDir: "build/static",
      sha256: createHash("sha256").update(contents).digest("hex")
    })
  );
}

test("installs verified gateway bundles and atomically rolls back", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-release-"));
  try {
    const first = path.join(sandbox, "first");
    const second = path.join(sandbox, "second");
    const stateDir = path.join(sandbox, "state");
    await createBundle(first, "1.0.0", "first-binary");
    await createBundle(second, "1.1.0", "second-binary");

    await installGatewayBundle(stateDir, first, ["test-target"]);
    await installGatewayBundle(stateDir, second, ["test-target"]);
    let resolved = await resolveInstalledGatewayRelease(stateDir, ["test-target"]);
    assert.equal(resolved.version, "1.1.0");

    await rollbackGatewayRelease(stateDir);
    resolved = await resolveInstalledGatewayRelease(stateDir, ["test-target"]);
    assert.equal(resolved.version, "1.0.0");
    const state = await readGatewayReleaseState(stateDir);
    assert.equal(state.previous.version, "1.1.0");
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("rejects a gateway bundle whose binary digest changed", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-release-tamper-"));
  try {
    const bundle = path.join(sandbox, "bundle");
    await createBundle(bundle, "1.0.0", "verified");
    await fs.writeFile(path.join(bundle, "dist", "backend", "test-target", "backend"), "tampered");
    await assert.rejects(() => installGatewayBundle(path.join(sandbox, "state"), bundle, ["test-target"]), /SHA-256/u);
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("refuses to reuse a corrupt installed release directory", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-release-reuse-"));
  try {
    const bundle = path.join(sandbox, "bundle");
    const stateDir = path.join(sandbox, "state");
    await createBundle(bundle, "1.0.0", "verified");
    const installed = await installGatewayBundle(stateDir, bundle, ["test-target"]);
    const installedBinary = path.join(installed.current.root, installed.current.binary);
    await fs.writeFile(installedBinary, "corrupt-installed-copy");

    await assert.rejects(
      () => installGatewayBundle(stateDir, bundle, ["test-target"]),
      /SHA-256 verification failed/u
    );
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("recovers a corrupted gateway release state from its previous snapshot", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-state-recovery-"));
  try {
    const first = path.join(sandbox, "first");
    const second = path.join(sandbox, "second");
    const stateDir = path.join(sandbox, "state");
    await createBundle(first, "1.0.0", "first-binary");
    await createBundle(second, "1.1.0", "second-binary");
    await installGatewayBundle(stateDir, first, ["test-target"]);
    await installGatewayBundle(stateDir, second, ["test-target"]);

    const statePath = path.join(stateDir, "gateway-release-state.json");
    await fs.writeFile(statePath, "{broken json");
    const recovered = await readGatewayReleaseState(stateDir);

    assert.equal(recovered.current.version, "1.0.0");
    assert.deepEqual(JSON.parse(await fs.readFile(statePath, "utf8")), recovered);
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("fails explicitly when gateway release state and backup are both invalid", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-state-corrupt-"));
  try {
    await fs.writeFile(path.join(sandbox, "gateway-release-state.json"), "{broken active");
    await fs.writeFile(path.join(sandbox, "gateway-release-state.json.bak"), "{broken backup");

    await assert.rejects(
      () => readGatewayReleaseState(sandbox),
      /Gateway release state is corrupted and no valid backup is available/u
    );
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("waits until the replacement gateway reports ready", async () => {
  let clock = 0;
  let probes = 0;
  const result = await waitForGatewayReadiness({
    pid: 42,
    probe: async () => {
      probes += 1;
      return probes === 3;
    },
    isProcessRunning: () => true,
    timeoutMs: 100,
    intervalMs: 10,
    now: () => clock,
    sleep: async (durationMs) => {
      clock += durationMs;
    }
  });

  assert.deepEqual(result, { attempts: 3, elapsedMs: 20 });
});

test("fails readiness immediately when the replacement gateway exits", async () => {
  let probeCalled = false;
  await assert.rejects(
    () =>
      waitForGatewayReadiness({
        pid: 99,
        probe: async () => {
          probeCalled = true;
          return true;
        },
        isProcessRunning: () => false,
        timeoutMs: 100,
        intervalMs: 10
      }),
    /Gateway process 99 exited before readiness/u
  );
  assert.equal(probeCalled, false);
});

test("times out readiness with the last probe error", async () => {
  let clock = 0;
  await assert.rejects(
    () =>
      waitForGatewayReadiness({
        pid: 7,
        probe: async () => {
          throw new Error("connection refused");
        },
        isProcessRunning: () => true,
        timeoutMs: 25,
        intervalMs: 10,
        now: () => clock,
        sleep: async (durationMs) => {
          clock += durationMs;
        }
      }),
    /Gateway did not become ready within 25 ms\. Last probe error: connection refused/u
  );
});

test("restores and starts the previous release when replacement readiness fails", async () => {
  const calls = [];
  await assert.rejects(
    () =>
      restartGatewayWithReleaseRecovery({
        restartGateway: async () => {
          calls.push("restart-replacement");
          throw new Error("replacement exited before readiness");
        },
        restoreReleaseState: async () => {
          calls.push("restore-state");
        },
        startRestoredGateway: async () => {
          calls.push("start-previous");
        }
      }),
    /previous release was restored: replacement exited before readiness/u
  );
  assert.deepEqual(calls, ["restart-replacement", "restore-state", "start-previous"]);
});
