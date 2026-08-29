import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  acquireGatewayStartLock,
  MAX_GATEWAY_START_LOCK_BYTES
} from "./gateway-start-lock.mjs";

async function withSandbox(callback) {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-gateway-start-lock-"));
  try {
    await callback(path.join(sandbox, "gateway-data-maintenance.lock"));
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
}

test("recovers a stale gateway maintenance lock", async () => {
  await withSandbox(async (lockPath) => {
    await fs.writeFile(lockPath, `${JSON.stringify({ pid: 22001, nonce: "stale-owner-token" })}\n`);

    const release = await acquireGatewayStartLock({
      lockPath,
      pid: 22002,
      isProcessActive: () => false,
      createToken: () => "replacement-owner-token"
    });

    const { createdAt, ...record } = JSON.parse(await fs.readFile(lockPath, "utf8"));
    assert.deepEqual(record, {
      pid: 22002,
      token: "replacement-owner-token",
      operation: "gateway-start"
    });
    assert.match(createdAt, /^\d{4}-\d{2}-\d{2}T/u);
    assert.equal(await release(), true);
    await assert.rejects(fs.access(lockPath), { code: "ENOENT" });
  });
});

test("does not preempt an active gateway maintenance lock", async () => {
  await withSandbox(async (lockPath) => {
    const activeLock = `${JSON.stringify({ pid: 23001, nonce: "active-owner-token" })}\n`;
    await fs.writeFile(lockPath, activeLock);

    await assert.rejects(
      acquireGatewayStartLock({
        lockPath,
        pid: 23002,
        isProcessActive: (pid) => pid === 23001,
        createToken: () => "contending-owner-token"
      }),
      /active \(PID 23001\)/u
    );
    assert.equal(await fs.readFile(lockPath, "utf8"), activeLock);
  });
});

test("recovers a stale lock whose PID was reused by the current launcher", async () => {
  await withSandbox(async (lockPath) => {
    await fs.writeFile(
      lockPath,
      `${JSON.stringify({ pid: 23501, token: "previous-process-token" })}\n`
    );

    const release = await acquireGatewayStartLock({
      lockPath,
      pid: 23501,
      isProcessActive: () => true,
      createToken: () => "reused-pid-owner-token"
    });

    assert.equal(JSON.parse(await fs.readFile(lockPath, "utf8")).token, "reused-pid-owner-token");
    assert.equal(await release(), true);
  });
});

test("release preserves a lock now owned by another process", async () => {
  await withSandbox(async (lockPath) => {
    const release = await acquireGatewayStartLock({
      lockPath,
      pid: 24001,
      isProcessActive: () => false,
      createToken: () => "original-owner-token"
    });
    const replacement = `${JSON.stringify({ pid: 24002, token: "replacement-owner-token" })}\n`;
    await fs.writeFile(lockPath, replacement);

    assert.equal(await release(), false);
    assert.equal(await fs.readFile(lockPath, "utf8"), replacement);
  });
});

test("recovers an old malformed maintenance lock without unbounded reads", async () => {
  await withSandbox(async (lockPath) => {
    await fs.writeFile(lockPath, Buffer.alloc(MAX_GATEWAY_START_LOCK_BYTES + 512, "x"));
    const old = new Date(Date.now() - 60_000);
    await fs.utimes(lockPath, old, old);

    const release = await acquireGatewayStartLock({
      lockPath,
      pid: 25001,
      isProcessActive: () => false,
      createToken: () => "malformed-lock-recovery"
    });

    assert.equal(JSON.parse(await fs.readFile(lockPath, "utf8")).pid, 25001);
    assert.equal(await release(), true);
  });
});

test("does not remove a fresh malformed lock that may still be written", async () => {
  await withSandbox(async (lockPath) => {
    const currentTime = Date.now();
    await fs.writeFile(lockPath, "{");
    await fs.utimes(lockPath, new Date(currentTime), new Date(currentTime));

    await assert.rejects(
      acquireGatewayStartLock({
        lockPath,
        pid: 26001,
        isProcessActive: () => false,
        createToken: () => "fresh-malformed-lock",
        now: () => currentTime
      }),
      /still being created/u
    );
    assert.equal(await fs.readFile(lockPath, "utf8"), "{");
  });
});
