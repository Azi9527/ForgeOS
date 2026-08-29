import { randomBytes } from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

export const MAX_GATEWAY_START_LOCK_BYTES = 4 * 1024;

const DEFAULT_MAX_ATTEMPTS = 3;
const MALFORMED_LOCK_GRACE_MS = 5_000;

function defaultToken() {
  return randomBytes(24).toString("base64url");
}

export function gatewayLockProcessIsActive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code !== "ESRCH";
  }
}

async function readBoundedLockSnapshot(lockPath) {
  let handle;
  try {
    handle = await fs.open(lockPath, "r");
    const stat = await handle.stat();
    const buffer = Buffer.alloc(MAX_GATEWAY_START_LOCK_BYTES + 1);
    let bytesRead = 0;
    while (bytesRead < buffer.length) {
      const result = await handle.read(buffer, bytesRead, buffer.length - bytesRead, bytesRead);
      if (result.bytesRead === 0) {
        break;
      }
      bytesRead += result.bytesRead;
    }
    const raw = buffer.subarray(0, bytesRead);
    let record = null;
    let malformed = stat.size > MAX_GATEWAY_START_LOCK_BYTES || bytesRead > MAX_GATEWAY_START_LOCK_BYTES;
    if (!malformed) {
      try {
        const parsed = JSON.parse(raw.toString("utf8"));
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          record = parsed;
          const token = parsed.token ?? parsed.nonce;
          malformed =
            !Number.isSafeInteger(parsed.pid) ||
            parsed.pid <= 0 ||
            typeof token !== "string" ||
            token.length === 0 ||
            token.length > 256;
        } else {
          malformed = true;
        }
      } catch {
        malformed = true;
      }
    }
    return {
      raw,
      size: stat.size,
      mtimeMs: stat.mtimeMs,
      dev: stat.dev,
      ino: stat.ino,
      malformed,
      record
    };
  } finally {
    await handle?.close().catch(() => {});
  }
}

function snapshotsMatch(left, right) {
  return (
    left.size === right.size &&
    left.mtimeMs === right.mtimeMs &&
    left.dev === right.dev &&
    left.ino === right.ino &&
    left.raw.equals(right.raw)
  );
}

function lockOwnerToken(record) {
  const value = record?.token ?? record?.nonce;
  return typeof value === "string" ? value : "";
}

async function removeUnchangedLock(lockPath, snapshot) {
  let current;
  try {
    current = await readBoundedLockSnapshot(lockPath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return true;
    }
    throw error;
  }
  if (!snapshotsMatch(snapshot, current)) {
    return false;
  }
  try {
    await fs.unlink(lockPath);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") {
      return true;
    }
    throw error;
  }
}

async function releaseOwnedGatewayStartLock(lockPath, owner) {
  let snapshot;
  try {
    snapshot = await readBoundedLockSnapshot(lockPath);
  } catch (error) {
    if (error?.code === "ENOENT") {
      return false;
    }
    throw error;
  }
  if (
    snapshot.malformed ||
    snapshot.record?.pid !== owner.pid ||
    lockOwnerToken(snapshot.record) !== owner.token
  ) {
    return false;
  }
  return removeUnchangedLock(lockPath, snapshot);
}

export async function acquireGatewayStartLock({
  lockPath,
  pid = process.pid,
  isProcessActive = gatewayLockProcessIsActive,
  createToken = defaultToken,
  now = Date.now,
  maxAttempts = DEFAULT_MAX_ATTEMPTS
}) {
  if (!path.isAbsolute(lockPath)) {
    throw new Error("Gateway maintenance lock path must be absolute.");
  }
  if (!Number.isSafeInteger(pid) || pid <= 0) {
    throw new Error("Gateway maintenance lock PID must be a positive integer.");
  }
  await fs.mkdir(path.dirname(lockPath), { recursive: true });

  const token = createToken();
  if (typeof token !== "string" || token.length < 16 || token.length > 256) {
    throw new Error("Gateway maintenance lock token is invalid.");
  }

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    let handle;
    let created = false;
    try {
      handle = await fs.open(lockPath, "wx", 0o600);
      created = true;
      await handle.writeFile(
        `${JSON.stringify({ pid, token, operation: "gateway-start", createdAt: new Date(now()).toISOString() })}\n`
      );
      await handle.sync();
      await handle.close();
      handle = null;
      const owner = { pid, token };
      return () => releaseOwnedGatewayStartLock(lockPath, owner);
    } catch (error) {
      await handle?.close().catch(() => {});
      if (created) {
        await fs.unlink(lockPath).catch(() => {});
      }
      if (error?.code !== "EEXIST") {
        throw error;
      }

      let existing;
      try {
        existing = await readBoundedLockSnapshot(lockPath);
      } catch (readError) {
        if (readError?.code === "ENOENT") {
          continue;
        }
        throw readError;
      }

      const existingPid = existing.record?.pid;
      if (
        Number.isSafeInteger(existingPid) &&
        existingPid > 0 &&
        existingPid !== pid &&
        isProcessActive(existingPid)
      ) {
        throw new Error(`Gateway data backup or restore is active (PID ${existingPid}); refusing to start the gateway.`);
      }
      if (existing.malformed && now() - existing.mtimeMs < MALFORMED_LOCK_GRACE_MS) {
        throw new Error("Gateway data maintenance lock is still being created; retry gateway startup shortly.");
      }
      await removeUnchangedLock(lockPath, existing);
    }
  }
  throw new Error("Could not acquire the gateway data maintenance lock after bounded recovery attempts.");
}
