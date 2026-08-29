import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";

export const GATEWAY_RELEASE_SCHEMA_VERSION = 1;
const GATEWAY_RELEASE_STATE_FILE = "gateway-release-state.json";
const GATEWAY_RELEASE_STATE_BACKUP_FILE = `${GATEWAY_RELEASE_STATE_FILE}.bak`;

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

async function writeFileAtomic(filePath, contents) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  try {
    await fs.writeFile(temporaryPath, contents, "utf8");
    await fs.rename(temporaryPath, filePath);
  } finally {
    await fs.rm(temporaryPath, { force: true });
  }
}

async function writeJsonAtomic(filePath, value) {
  await writeFileAtomic(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

async function sha256(filePath) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filePath)) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}

function safeBundlePath(bundleRoot, relativePath, label) {
  const resolvedRoot = path.resolve(bundleRoot);
  const resolved = path.resolve(resolvedRoot, String(relativePath ?? ""));
  const relative = path.relative(resolvedRoot, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`${label} must be a file or directory inside the gateway bundle.`);
  }
  return resolved;
}

function sanitizeReleasePart(value) {
  return String(value ?? "")
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
}

function defaultGatewayReleaseState() {
  return { schemaVersion: GATEWAY_RELEASE_SCHEMA_VERSION, current: null, previous: null };
}

function validateGatewayReleaseRecord(record, label) {
  if (record === null) {
    return;
  }
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new Error(`${label} must be an object or null.`);
  }
  for (const field of ["id", "version", "target", "root", "binary", "staticDir"]) {
    if (typeof record[field] !== "string" || record[field].trim() === "") {
      throw new Error(`${label}.${field} must be a non-empty string.`);
    }
  }
  if (!/^[a-f0-9]{64}$/u.test(String(record.sha256 ?? "").toLowerCase())) {
    throw new Error(`${label}.sha256 must be a SHA-256 digest.`);
  }
}

function validateGatewayReleaseState(value, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  if (value.schemaVersion !== GATEWAY_RELEASE_SCHEMA_VERSION) {
    throw new Error(`${label} has unsupported schema version ${value.schemaVersion ?? "missing"}.`);
  }
  validateGatewayReleaseRecord(value.current ?? null, `${label}.current`);
  validateGatewayReleaseRecord(value.previous ?? null, `${label}.previous`);
  return value;
}

async function readGatewayReleaseStateCandidate(filePath, label) {
  let raw;
  try {
    raw = await fs.readFile(filePath, "utf8");
  } catch (error) {
    if (error?.code === "ENOENT") {
      return { exists: false, state: null, error: null };
    }
    return { exists: true, state: null, error: new Error(`${label} could not be read: ${errorMessage(error)}`) };
  }
  try {
    return {
      exists: true,
      state: validateGatewayReleaseState(JSON.parse(raw), label),
      error: null
    };
  } catch (error) {
    return { exists: true, state: null, error: new Error(`${label} is invalid: ${errorMessage(error)}`) };
  }
}

function gatewayReleaseStatePaths(stateDir) {
  return {
    statePath: path.join(stateDir, GATEWAY_RELEASE_STATE_FILE),
    backupPath: path.join(stateDir, GATEWAY_RELEASE_STATE_BACKUP_FILE)
  };
}

export async function waitForGatewayReadiness({
  pid,
  probe,
  isProcessRunning,
  timeoutMs = 30_000,
  intervalMs = 250,
  now = Date.now,
  sleep = (durationMs) => new Promise((resolve) => setTimeout(resolve, durationMs))
}) {
  if (typeof probe !== "function" || typeof isProcessRunning !== "function") {
    throw new Error("Gateway readiness requires probe and isProcessRunning functions.");
  }
  const boundedTimeoutMs = Math.max(1, Number(timeoutMs) || 0);
  const boundedIntervalMs = Math.max(1, Number(intervalMs) || 0);
  const startedAt = now();
  let attempts = 0;
  let lastError = null;

  while (now() - startedAt < boundedTimeoutMs) {
    if (!(await isProcessRunning(pid))) {
      throw new Error(`Gateway process ${pid ?? "unknown"} exited before readiness.`);
    }
    attempts += 1;
    try {
      if (await probe()) {
        return { attempts, elapsedMs: Math.max(0, now() - startedAt) };
      }
    } catch (error) {
      lastError = error;
    }
    const remainingMs = boundedTimeoutMs - (now() - startedAt);
    if (remainingMs <= 0) {
      break;
    }
    await sleep(Math.min(boundedIntervalMs, remainingMs));
  }

  if (!(await isProcessRunning(pid))) {
    throw new Error(`Gateway process ${pid ?? "unknown"} exited before readiness.`);
  }
  const details = lastError ? ` Last probe error: ${errorMessage(lastError)}` : "";
  throw new Error(`Gateway did not become ready within ${boundedTimeoutMs} ms.${details}`);
}

export async function restartGatewayWithReleaseRecovery({
  restartGateway,
  restoreReleaseState,
  startRestoredGateway
}) {
  try {
    return await restartGateway();
  } catch (switchError) {
    try {
      await restoreReleaseState();
    } catch (restoreError) {
      throw new Error(
        `Gateway switch failed (${errorMessage(switchError)}) and the previous release state could not be restored: ${errorMessage(restoreError)}`
      );
    }
    try {
      await startRestoredGateway();
    } catch (restartError) {
      throw new Error(
        `Gateway switch failed (${errorMessage(switchError)}); the previous release state was restored, but its gateway could not start: ${errorMessage(restartError)}`
      );
    }
    throw new Error(`Gateway switch failed and the previous release was restored: ${errorMessage(switchError)}`);
  }
}

async function assertSafeBundleTree(directory) {
  const rootStats = await fs.lstat(directory);
  if (!rootStats.isDirectory() || rootStats.isSymbolicLink()) {
    throw new Error("Static frontend path must be a real directory inside the gateway bundle.");
  }
  const pending = [directory];
  while (pending.length > 0) {
    const current = pending.pop();
    const entries = await fs.readdir(current, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isSymbolicLink()) {
        throw new Error("Gateway bundles may not contain symbolic links.");
      }
      if (entry.isDirectory()) {
        pending.push(path.join(current, entry.name));
      }
    }
  }
}

export async function inspectGatewayBundle(bundleRoot, acceptedTargets) {
  const manifestPath = path.join(bundleRoot, "forgeos-gateway.json");
  const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  if (manifest.schemaVersion !== GATEWAY_RELEASE_SCHEMA_VERSION) {
    throw new Error(`Unsupported gateway bundle schema: ${manifest.schemaVersion ?? "missing"}.`);
  }
  const version = sanitizeReleasePart(manifest.version);
  const target = sanitizeReleasePart(manifest.target);
  if (!version || !target) {
    throw new Error("Gateway bundle version and target are required.");
  }
  if (!acceptedTargets.includes(target)) {
    throw new Error(`Gateway bundle target ${target} does not match this platform (${acceptedTargets.join(", ")}).`);
  }
  const binaryPath = safeBundlePath(bundleRoot, manifest.binary, "Gateway binary");
  const staticDir = safeBundlePath(bundleRoot, manifest.staticDir, "Static frontend directory");
  const binaryStats = await fs.lstat(binaryPath);
  if (!binaryStats.isFile() || binaryStats.isSymbolicLink()) {
    throw new Error("Gateway binary must be a regular file inside the bundle.");
  }
  await assertSafeBundleTree(staticDir);
  const expectedSha256 = String(manifest.sha256 ?? "").trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/u.test(expectedSha256)) {
    throw new Error("Gateway bundle is missing a valid SHA-256 digest.");
  }
  const actualSha256 = await sha256(binaryPath);
  if (actualSha256 !== expectedSha256) {
    throw new Error("Gateway binary SHA-256 verification failed.");
  }
  await fs.access(path.join(staticDir, "index.html"));
  return {
    manifest: { ...manifest, version, target, sha256: actualSha256 },
    manifestPath,
    binaryPath,
    staticDir
  };
}

export async function readGatewayReleaseState(stateDir) {
  const { statePath, backupPath } = gatewayReleaseStatePaths(stateDir);
  const active = await readGatewayReleaseStateCandidate(statePath, "Gateway release state");
  if (active.state) {
    return active.state;
  }

  const backup = await readGatewayReleaseStateCandidate(backupPath, "Gateway release state backup");
  if (backup.state) {
    await writeJsonAtomic(statePath, backup.state);
    return backup.state;
  }
  if (!active.exists && !backup.exists) {
    return defaultGatewayReleaseState();
  }

  const reasons = [active.error, backup.error].filter(Boolean).map(errorMessage).join(" ");
  throw new Error(`Gateway release state is corrupted and no valid backup is available. ${reasons}`.trim());
}

export async function writeGatewayReleaseState(stateDir, state) {
  const validated = validateGatewayReleaseState(state, "Gateway release state");
  const { statePath, backupPath } = gatewayReleaseStatePaths(stateDir);
  const active = await readGatewayReleaseStateCandidate(statePath, "Gateway release state");
  if (active.exists && !active.state) {
    throw new Error(
      `Refusing to overwrite an invalid gateway release state. ${active.error ? errorMessage(active.error) : ""}`.trim()
    );
  }
  if (active.state) {
    await writeJsonAtomic(backupPath, active.state);
  }
  await writeJsonAtomic(statePath, validated);
}

export async function installGatewayBundle(stateDir, bundleRoot, acceptedTargets) {
  const inspected = await inspectGatewayBundle(bundleRoot, acceptedTargets);
  const releaseId = `${inspected.manifest.version}-${inspected.manifest.sha256.slice(0, 12)}`;
  const releasesRoot = path.join(stateDir, "gateway-releases");
  const releaseRoot = path.join(releasesRoot, releaseId);
  const temporaryRoot = `${releaseRoot}.${process.pid}.${Date.now()}.tmp`;
  await fs.mkdir(releasesRoot, { recursive: true });

  let existingRelease = null;
  try {
    existingRelease = await fs.lstat(releaseRoot);
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
  if (existingRelease) {
    if (!existingRelease.isDirectory() || existingRelease.isSymbolicLink()) {
      throw new Error("Installed gateway release path must be a real directory.");
    }
    const installed = await inspectGatewayBundle(releaseRoot, acceptedTargets);
    for (const field of ["version", "target", "sha256", "binary", "staticDir"]) {
      if (installed.manifest[field] !== inspected.manifest[field]) {
        throw new Error(`Installed gateway release does not match the requested bundle (${field}).`);
      }
    }
  } else {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
    try {
      await fs.mkdir(temporaryRoot, { recursive: true });
      await fs.copyFile(inspected.manifestPath, path.join(temporaryRoot, "forgeos-gateway.json"));
      const binaryRelativePath = path.relative(bundleRoot, inspected.binaryPath);
      const staticRelativePath = path.relative(bundleRoot, inspected.staticDir);
      const installedBinary = path.join(temporaryRoot, binaryRelativePath);
      const installedStatic = path.join(temporaryRoot, staticRelativePath);
      await fs.mkdir(path.dirname(installedBinary), { recursive: true });
      await fs.copyFile(inspected.binaryPath, installedBinary);
      await fs.mkdir(path.dirname(installedStatic), { recursive: true });
      await fs.cp(inspected.staticDir, installedStatic, { recursive: true });
      await fs.rename(temporaryRoot, releaseRoot);
    } catch (error) {
      await fs.rm(temporaryRoot, { recursive: true, force: true }).catch(() => {});
      throw error;
    }
  }

  const currentState = await readGatewayReleaseState(stateDir);
  const release = {
    id: releaseId,
    version: inspected.manifest.version,
    target: inspected.manifest.target,
    sha256: inspected.manifest.sha256,
    root: releaseRoot,
    binary: inspected.manifest.binary,
    staticDir: inspected.manifest.staticDir,
    installedAt: new Date().toISOString()
  };
  const nextState = {
    schemaVersion: GATEWAY_RELEASE_SCHEMA_VERSION,
    current: release,
    previous: currentState.current?.id === release.id ? currentState.previous ?? null : currentState.current ?? null
  };
  await writeGatewayReleaseState(stateDir, nextState);
  return nextState;
}

export async function rollbackGatewayRelease(stateDir) {
  const currentState = await readGatewayReleaseState(stateDir);
  if (!currentState.previous) {
    throw new Error("No previous gateway release is available for rollback.");
  }
  const nextState = {
    schemaVersion: GATEWAY_RELEASE_SCHEMA_VERSION,
    current: currentState.previous,
    previous: currentState.current ?? null
  };
  await writeGatewayReleaseState(stateDir, nextState);
  return nextState;
}

export async function resolveInstalledGatewayRelease(stateDir, acceptedTargets) {
  const state = await readGatewayReleaseState(stateDir);
  const release = state.current;
  if (!release || !acceptedTargets.includes(release.target)) {
    return null;
  }
  const binaryPath = safeBundlePath(release.root, release.binary, "Installed gateway binary");
  const staticDir = safeBundlePath(release.root, release.staticDir, "Installed static frontend directory");
  if ((await sha256(binaryPath)) !== release.sha256) {
    throw new Error("Installed gateway binary failed SHA-256 verification.");
  }
  await fs.access(path.join(staticDir, "index.html"));
  return { ...release, binaryPath, staticDir };
}
