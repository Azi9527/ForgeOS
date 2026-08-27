import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  installGatewayBundle,
  readGatewayReleaseState,
  resolveInstalledGatewayRelease,
  rollbackGatewayRelease
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
