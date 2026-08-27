import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";

export const GATEWAY_RELEASE_SCHEMA_VERSION = 1;

async function writeJsonAtomic(filePath, value) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const temporaryPath = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
  await fs.rename(temporaryPath, filePath);
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
  try {
    return JSON.parse(await fs.readFile(path.join(stateDir, "gateway-release-state.json"), "utf8"));
  } catch {
    return { schemaVersion: GATEWAY_RELEASE_SCHEMA_VERSION, current: null, previous: null };
  }
}

export async function writeGatewayReleaseState(stateDir, state) {
  await writeJsonAtomic(path.join(stateDir, "gateway-release-state.json"), state);
}

export async function installGatewayBundle(stateDir, bundleRoot, acceptedTargets) {
  const inspected = await inspectGatewayBundle(bundleRoot, acceptedTargets);
  const releaseId = `${inspected.manifest.version}-${inspected.manifest.sha256.slice(0, 12)}`;
  const releasesRoot = path.join(stateDir, "gateway-releases");
  const releaseRoot = path.join(releasesRoot, releaseId);
  const temporaryRoot = `${releaseRoot}.${process.pid}.${Date.now()}.tmp`;
  await fs.mkdir(releasesRoot, { recursive: true });

  try {
    await fs.access(path.join(releaseRoot, "forgeos-gateway.json"));
  } catch {
    await fs.rm(temporaryRoot, { recursive: true, force: true });
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
