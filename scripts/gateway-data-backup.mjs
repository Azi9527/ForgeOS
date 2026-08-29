import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

import YAML from "yaml";

export const GATEWAY_DATA_BACKUP_SCHEMA_VERSION = 1;

const BACKUP_KIND = "forgeos-gateway-business-data";
const MANIFEST_FILE = "manifest.json";
const PAYLOAD_DIRECTORY = "data";
const AUDIT_FILES = ["audit-log.jsonl", "audit-log.jsonl.1"];
const INCLUDED_SCOPE = ["configured profile data directories", ...AUDIT_FILES.map((name) => `global/${name}`)];
const EXCLUDED_SCOPE = [
  "CODEX_HOME/**",
  "auth.json",
  "config.toml",
  "sessions/**",
  "archived_sessions/**",
  "state_5.sqlite",
  "session_index.jsonl",
  "notification webhook credential fields"
];
const MAX_MANIFEST_BYTES = 16 * 1024 * 1024;
const MAX_MANIFEST_FILES = 1_000_000;
const MAINTENANCE_LOCK_FILE = "gateway-data-maintenance.lock";

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function sanitizeProfileId(input) {
  const normalized = String(input ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/gu, "-")
    .replace(/^-+|-+$/gu, "");
  return normalized || "default";
}

function profileIdIsPortable(id) {
  return (
    /^[a-z0-9._-]+$/u.test(id) &&
    id !== "." &&
    id !== ".." &&
    !id.endsWith(".") &&
    !/^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/iu.test(id)
  );
}

function expandHome(input, homeDirectory) {
  const value = String(input ?? "");
  if (value === "~") {
    return homeDirectory;
  }
  if (value.startsWith("~/") || value.startsWith("~\\")) {
    return path.join(homeDirectory, value.slice(2));
  }
  return value;
}

function pathsOverlap(left, right) {
  const relative = path.relative(path.resolve(left), path.resolve(right));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function assertSafeProfileLayout(config) {
  for (const profile of config.profiles) {
    if (path.resolve(profile.dataDir) === path.resolve(config.dataDir)) {
      throw new Error(`Profile ${profile.id} data directory must not be the global data directory.`);
    }
    for (const candidate of config.profiles) {
      if (pathsOverlap(profile.dataDir, candidate.codexHome)) {
        throw new Error(
          `Profile ${profile.id} data directory contains CODEX_HOME for profile ${candidate.id}; refusing to risk backing up external credentials.`
        );
      }
    }
  }
  for (let index = 0; index < config.profiles.length; index += 1) {
    for (let otherIndex = index + 1; otherIndex < config.profiles.length; otherIndex += 1) {
      const left = config.profiles[index];
      const right = config.profiles[otherIndex];
      if (pathsOverlap(left.dataDir, right.dataDir) || pathsOverlap(right.dataDir, left.dataDir)) {
        throw new Error(`Profile data directories overlap: ${left.id} and ${right.id}.`);
      }
    }
  }
}

export function normalizeGatewayDataConfig(rawConfig = {}, homeDirectory = os.homedir()) {
  const defaultDataDir = path.join(homeDirectory, ".codex", "codex-webui", "data");
  const defaultCodexHome = path.join(homeDirectory, ".codex");
  const dataDir = path.resolve(expandHome(rawConfig.dataDir ?? rawConfig.data_dir ?? defaultDataDir, homeDirectory));
  const codexHome = path.resolve(
    expandHome(rawConfig.codexHome ?? rawConfig.codex_home ?? defaultCodexHome, homeDirectory)
  );
  const rawProfiles = Array.isArray(rawConfig.profiles) ? rawConfig.profiles : [];
  const fallbackProfileId = sanitizeProfileId(rawConfig.defaultProfileId ?? rawConfig.default_profile_id);
  const profiles = [];
  const seen = new Set();

  for (const [index, entry] of rawProfiles.entries()) {
    const id = sanitizeProfileId(entry?.id ?? (index === 0 ? fallbackProfileId : `profile-${index + 1}`));
    if (!profileIdIsPortable(id) || seen.has(id)) {
      if (seen.has(id)) {
        continue;
      }
      throw new Error(`Unsafe profile id: ${id}.`);
    }
    seen.add(id);
    profiles.push({
      id,
      codexHome: path.resolve(expandHome(entry?.codexHome ?? entry?.codex_home ?? codexHome, homeDirectory)),
      dataDir: path.resolve(
        expandHome(entry?.dataDir ?? entry?.data_dir ?? path.join(dataDir, "profiles", id), homeDirectory)
      )
    });
  }

  if (profiles.length === 0) {
    if (!profileIdIsPortable(fallbackProfileId)) {
      throw new Error(`Unsafe profile id: ${fallbackProfileId}.`);
    }
    profiles.push({
      id: fallbackProfileId,
      codexHome,
      dataDir: path.join(dataDir, "profiles", fallbackProfileId)
    });
  }

  const config = { dataDir, profiles };
  assertSafeProfileLayout(config);
  return config;
}

export async function readGatewayDataConfig(configPath) {
  const raw = await fs.readFile(configPath, "utf8");
  const parsed = YAML.parse(raw);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Gateway configuration must be a YAML object.");
  }
  return normalizeGatewayDataConfig(parsed);
}

async function pathKind(filePath) {
  try {
    const stats = await fs.lstat(filePath);
    if (stats.isSymbolicLink()) {
      return "symlink";
    }
    if (stats.isDirectory()) {
      return "directory";
    }
    if (stats.isFile()) {
      return "file";
    }
    return "special";
  } catch (error) {
    if (error?.code === "ENOENT") {
      return "missing";
    }
    throw error;
  }
}

function defaultRuntimeStateDir() {
  return path.join(os.homedir(), ".codex", "codex-webui");
}

function processIsRunning(pid) {
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

async function activeGatewayPids(runtimeStateDir) {
  const candidates = new Set();
  try {
    const pid = Number.parseInt((await fs.readFile(path.join(runtimeStateDir, "server.pid"), "utf8")).trim(), 10);
    if (Number.isSafeInteger(pid) && pid > 0) {
      candidates.add(pid);
    }
  } catch (error) {
    if (error?.code !== "ENOENT") {
      throw error;
    }
  }
  try {
    const metadata = JSON.parse(await fs.readFile(path.join(runtimeStateDir, "server.json"), "utf8"));
    if (Number.isSafeInteger(metadata?.pid) && metadata.pid > 0) {
      candidates.add(metadata.pid);
    }
  } catch (error) {
    if (error?.code !== "ENOENT" && !(error instanceof SyntaxError)) {
      throw error;
    }
  }
  return [...candidates].filter(processIsRunning);
}

async function acquireGatewayDataMaintenance(runtimeStateDir = defaultRuntimeStateDir()) {
  const resolvedRuntimeStateDir = path.resolve(runtimeStateDir);
  await fs.mkdir(resolvedRuntimeStateDir, { recursive: true });
  const lockPath = path.join(resolvedRuntimeStateDir, MAINTENANCE_LOCK_FILE);
  const nonce = randomUUID();

  for (let attempt = 0; attempt < 2; attempt += 1) {
    let handle;
    try {
      handle = await fs.open(lockPath, "wx", 0o600);
      await handle.writeFile(`${JSON.stringify({ pid: process.pid, nonce, createdAt: new Date().toISOString() })}\n`);
      await handle.sync();
      await handle.close();
      handle = null;
      const activePids = await activeGatewayPids(resolvedRuntimeStateDir);
      if (activePids.length > 0) {
        await fs.rm(lockPath, { force: true });
        throw new Error(`Stop the ForgeOS gateway before backup or restore (active PID ${activePids.join(", ")}).`);
      }
      return async () => {
        let current;
        try {
          current = JSON.parse(await fs.readFile(lockPath, "utf8"));
        } catch {
          return;
        }
        if (current?.nonce === nonce) {
          await fs.rm(lockPath, { force: true });
        }
      };
    } catch (error) {
      await handle?.close().catch(() => {});
      if (error?.code !== "EEXIST") {
        throw error;
      }
      let existing;
      try {
        existing = JSON.parse(await fs.readFile(lockPath, "utf8"));
      } catch {
        throw new Error(`Gateway data maintenance lock is invalid: ${lockPath}.`);
      }
      if (processIsRunning(existing?.pid)) {
        throw new Error(`Another gateway data maintenance operation is active (PID ${existing.pid}).`);
      }
      await fs.rm(lockPath, { force: true });
    }
  }
  throw new Error("Could not acquire the gateway data maintenance lock.");
}

function validateRelativePath(relativePath, label = "Backup path") {
  if (
    typeof relativePath !== "string" ||
    relativePath.length === 0 ||
    relativePath.length > 4096 ||
    relativePath.includes("\\") ||
    relativePath.includes(":") ||
    relativePath.includes("\0") ||
    path.posix.isAbsolute(relativePath)
  ) {
    throw new Error(`${label} is unsafe: ${String(relativePath)}.`);
  }
  const segments = relativePath.split("/");
  if (segments.some((segment) => segment === "" || segment === "." || segment === "..")) {
    throw new Error(`${label} contains path traversal: ${relativePath}.`);
  }
  return relativePath;
}

function payloadPath(backupRoot, relativePath) {
  validateRelativePath(relativePath);
  return path.join(backupRoot, PAYLOAD_DIRECTORY, ...relativePath.split("/"));
}

async function sha256(filePath) {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(filePath)) {
    hash.update(chunk);
  }
  return hash.digest("hex");
}

function isUiStateBackupPath(relativePath) {
  return /^profiles\/[^/]+\/ui-state\.json(?:\.bak)?$/u.test(relativePath);
}

function redactKnownExternalCredentials(value) {
  if (Array.isArray(value)) {
    for (const entry of value) {
      redactKnownExternalCredentials(entry);
    }
    return;
  }
  if (!value || typeof value !== "object") {
    return;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (key === "webhookUrl" || key === "slackWebhookUrl") {
      value[key] = null;
    } else {
      redactKnownExternalCredentials(entry);
    }
  }
}

async function collectTree(root, relativePrefix) {
  const kind = await pathKind(root);
  if (kind === "missing") {
    return [];
  }
  if (kind !== "directory") {
    throw new Error(`Backup source must be a real directory: ${root}.`);
  }
  const files = [];
  const pending = [{ directory: root, relative: relativePrefix }];
  while (pending.length > 0) {
    const current = pending.pop();
    const entries = await fs.readdir(current.directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const sourcePath = path.join(current.directory, entry.name);
      const relativePath = `${current.relative}/${entry.name}`;
      validateRelativePath(relativePath, "Profile data path");
      const entryKind = await pathKind(sourcePath);
      if (entryKind === "directory") {
        pending.push({ directory: sourcePath, relative: relativePath });
      } else if (entryKind === "file") {
        files.push({ sourcePath, relativePath });
      } else {
        throw new Error(`Profile data contains an unsupported ${entryKind}: ${sourcePath}.`);
      }
    }
  }
  return files;
}

async function copyDescribedFile(sourcePath, destinationPath, relativePath) {
  const before = await fs.lstat(sourcePath);
  if (!before.isFile() || before.isSymbolicLink()) {
    throw new Error(`Backup source is not a regular file: ${sourcePath}.`);
  }
  await fs.mkdir(path.dirname(destinationPath), { recursive: true });
  if (isUiStateBackupPath(relativePath)) {
    let parsed;
    try {
      parsed = JSON.parse(await fs.readFile(sourcePath, "utf8"));
    } catch (error) {
      throw new Error(`Cannot safely redact external credentials from ${sourcePath}: ${errorMessage(error)}`);
    }
    redactKnownExternalCredentials(parsed);
    await fs.writeFile(destinationPath, `${JSON.stringify(parsed, null, 2)}\n`);
  } else {
    await fs.copyFile(sourcePath, destinationPath);
  }
  const [sourceAfter, destinationDigest, copied] = await Promise.all([
    fs.lstat(sourcePath),
    sha256(destinationPath),
    fs.lstat(destinationPath)
  ]);
  if (before.size !== sourceAfter.size || before.mtimeMs !== sourceAfter.mtimeMs) {
    throw new Error(`Backup source changed while it was copied: ${sourcePath}.`);
  }
  if (!isUiStateBackupPath(relativePath) && (await sha256(sourcePath)) !== destinationDigest) {
    throw new Error(`Backup source changed while it was copied: ${sourcePath}.`);
  }
  const mode = before.mode & 0o777;
  await fs.chmod(destinationPath, mode);
  return { path: relativePath, size: copied.size, sha256: destinationDigest, mode };
}

function timestampPart(date) {
  return date.toISOString().replace(/[:.]/gu, "-");
}

function assertBackupDestinationOutsideProfiles(destinationRoot, config) {
  for (const profile of config.profiles) {
    if (pathsOverlap(profile.dataDir, destinationRoot)) {
      throw new Error(`Backup destination must be outside profile ${profile.id} data directory.`);
    }
  }
}

async function createGatewayDataBackupUnlocked({
  config: rawConfig,
  destinationRoot,
  purpose = "manual",
  now = () => new Date(),
  uniqueId = () => randomUUID()
}) {
  if (!destinationRoot) {
    throw new Error("A backup destination root is required.");
  }
  if (!new Set(["manual", "pre-restore"]).has(purpose)) {
    throw new Error(`Unsupported backup purpose: ${purpose}.`);
  }
  const config = normalizeGatewayDataConfig(rawConfig);
  const resolvedDestination = path.resolve(destinationRoot);
  assertBackupDestinationOutsideProfiles(resolvedDestination, config);
  await fs.mkdir(resolvedDestination, { recursive: true });

  const createdAt = now();
  if (!(createdAt instanceof Date) || Number.isNaN(createdAt.getTime())) {
    throw new Error("Backup timestamp is invalid.");
  }
  const suffix = String(uniqueId()).replace(/[^a-zA-Z0-9_-]/gu, "").slice(0, 12) || "backup";
  const name = `forgeos-gateway-data-v${GATEWAY_DATA_BACKUP_SCHEMA_VERSION}-${timestampPart(createdAt)}-${suffix}`;
  const backupPath = path.join(resolvedDestination, name);
  const stagingPath = path.join(resolvedDestination, `.forgeos-backup-stage-${suffix}`);
  if ((await pathKind(backupPath)) !== "missing" || (await pathKind(stagingPath)) !== "missing") {
    throw new Error(`Backup destination already exists: ${backupPath}.`);
  }

  try {
    await fs.mkdir(path.join(stagingPath, PAYLOAD_DIRECTORY), { recursive: true });
    const sources = [];
    for (const auditFile of AUDIT_FILES) {
      const sourcePath = path.join(config.dataDir, auditFile);
      const kind = await pathKind(sourcePath);
      if (kind === "file") {
        sources.push({ sourcePath, relativePath: `global/${auditFile}` });
      } else if (kind !== "missing") {
        throw new Error(`Audit source is not a regular file: ${sourcePath}.`);
      }
    }
    for (const profile of config.profiles) {
      sources.push(...(await collectTree(profile.dataDir, `profiles/${profile.id}`)));
    }
    sources.sort((left, right) => left.relativePath.localeCompare(right.relativePath));

    const files = [];
    for (const source of sources) {
      files.push(
        await copyDescribedFile(
          source.sourcePath,
          payloadPath(stagingPath, source.relativePath),
          source.relativePath
        )
      );
    }
    const manifest = {
      schemaVersion: GATEWAY_DATA_BACKUP_SCHEMA_VERSION,
      kind: BACKUP_KIND,
      purpose,
      createdAt: createdAt.toISOString(),
      scope: { included: INCLUDED_SCOPE, excluded: EXCLUDED_SCOPE },
      profiles: config.profiles.map((profile) => ({ id: profile.id, path: `profiles/${profile.id}` })),
      files
    };
    await fs.writeFile(path.join(stagingPath, MANIFEST_FILE), `${JSON.stringify(manifest, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600
    });
    await verifyGatewayDataBackup(stagingPath);
    await fs.rename(stagingPath, backupPath);
    return { backupPath, manifest };
  } catch (error) {
    await fs.rm(stagingPath, { recursive: true, force: true }).catch(() => {});
    throw error;
  }
}

export async function createGatewayDataBackup(options) {
  const releaseMaintenance = await acquireGatewayDataMaintenance(options?.runtimeStateDir);
  try {
    return await createGatewayDataBackupUnlocked(options);
  } finally {
    await releaseMaintenance();
  }
}

function assertObjectKeys(value, expectedKeys, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object.`);
  }
  const actual = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${label} has unsupported fields.`);
  }
}

function validateManifest(rawManifest) {
  assertObjectKeys(
    rawManifest,
    ["schemaVersion", "kind", "purpose", "createdAt", "scope", "profiles", "files"],
    "Backup manifest"
  );
  if (rawManifest.schemaVersion !== GATEWAY_DATA_BACKUP_SCHEMA_VERSION) {
    throw new Error(`Unsupported backup schema version: ${rawManifest.schemaVersion ?? "missing"}.`);
  }
  if (rawManifest.kind !== BACKUP_KIND) {
    throw new Error("Backup manifest kind is invalid.");
  }
  if (!new Set(["manual", "pre-restore"]).has(rawManifest.purpose)) {
    throw new Error("Backup manifest purpose is invalid.");
  }
  if (typeof rawManifest.createdAt !== "string" || Number.isNaN(Date.parse(rawManifest.createdAt))) {
    throw new Error("Backup manifest timestamp is invalid.");
  }
  assertObjectKeys(rawManifest.scope, ["included", "excluded"], "Backup manifest scope");
  if (
    JSON.stringify(rawManifest.scope.included) !== JSON.stringify(INCLUDED_SCOPE) ||
    JSON.stringify(rawManifest.scope.excluded) !== JSON.stringify(EXCLUDED_SCOPE)
  ) {
    throw new Error("Backup manifest scope is incompatible with this tool.");
  }
  if (!Array.isArray(rawManifest.profiles) || rawManifest.profiles.length === 0) {
    throw new Error("Backup manifest profiles must be a non-empty array.");
  }
  const profilePaths = new Set();
  const profileIds = new Set();
  for (const profile of rawManifest.profiles) {
    assertObjectKeys(profile, ["id", "path"], "Backup manifest profile");
    if (
      typeof profile.id !== "string" ||
      !profileIdIsPortable(profile.id) ||
      profile.id.length > 128 ||
      profileIds.has(profile.id)
    ) {
      throw new Error("Backup manifest contains an invalid or duplicate profile id.");
    }
    if (profile.path !== `profiles/${profile.id}`) {
      throw new Error(`Backup manifest profile path is invalid for ${profile.id}.`);
    }
    validateRelativePath(profile.path, "Backup profile path");
    profileIds.add(profile.id);
    profilePaths.add(profile.path);
  }
  if (!Array.isArray(rawManifest.files) || rawManifest.files.length > MAX_MANIFEST_FILES) {
    throw new Error("Backup manifest files must be a bounded array.");
  }
  const filePaths = new Set();
  for (const file of rawManifest.files) {
    assertObjectKeys(file, ["path", "size", "sha256", "mode"], "Backup manifest file");
    validateRelativePath(file.path, "Backup file path");
    const allowedGlobal = AUDIT_FILES.some((name) => file.path === `global/${name}`);
    const allowedProfile = [...profilePaths].some((profilePath) => file.path.startsWith(`${profilePath}/`));
    if ((!allowedGlobal && !allowedProfile) || filePaths.has(file.path)) {
      throw new Error(`Backup manifest file is outside the declared scope or duplicated: ${file.path}.`);
    }
    if (!Number.isSafeInteger(file.size) || file.size < 0) {
      throw new Error(`Backup manifest file size is invalid: ${file.path}.`);
    }
    if (typeof file.sha256 !== "string" || !/^[a-f0-9]{64}$/u.test(file.sha256)) {
      throw new Error(`Backup manifest digest is invalid: ${file.path}.`);
    }
    if (!Number.isInteger(file.mode) || file.mode < 0 || file.mode > 0o777) {
      throw new Error(`Backup manifest mode is invalid: ${file.path}.`);
    }
    filePaths.add(file.path);
  }
  return rawManifest;
}

async function listPayloadFiles(backupRoot) {
  const dataRoot = path.join(backupRoot, PAYLOAD_DIRECTORY);
  const entries = await collectTree(dataRoot, "payload");
  return entries.map((entry) => entry.relativePath.slice("payload/".length)).sort();
}

export async function verifyGatewayDataBackup(backupRoot) {
  const resolvedRoot = path.resolve(backupRoot);
  if ((await pathKind(resolvedRoot)) !== "directory") {
    throw new Error("Backup root must be a real directory.");
  }
  const rootEntries = (await fs.readdir(resolvedRoot)).sort();
  if (JSON.stringify(rootEntries) !== JSON.stringify([PAYLOAD_DIRECTORY, MANIFEST_FILE].sort())) {
    throw new Error("Backup root must contain exactly manifest.json and data/.");
  }
  if ((await pathKind(path.join(resolvedRoot, PAYLOAD_DIRECTORY))) !== "directory") {
    throw new Error("Backup payload root must be a real directory.");
  }
  const manifestPath = path.join(resolvedRoot, MANIFEST_FILE);
  const manifestStats = await fs.lstat(manifestPath);
  if (!manifestStats.isFile() || manifestStats.isSymbolicLink() || manifestStats.size > MAX_MANIFEST_BYTES) {
    throw new Error("Backup manifest must be a bounded regular file.");
  }
  let manifest;
  try {
    manifest = validateManifest(JSON.parse(await fs.readFile(manifestPath, "utf8")));
  } catch (error) {
    throw new Error(`Backup manifest is invalid: ${errorMessage(error)}`);
  }

  const physicalFiles = await listPayloadFiles(resolvedRoot);
  const declaredFiles = manifest.files.map((file) => file.path).sort();
  if (JSON.stringify(physicalFiles) !== JSON.stringify(declaredFiles)) {
    throw new Error("Backup payload does not exactly match the manifest.");
  }
  for (const file of manifest.files) {
    const filePath = payloadPath(resolvedRoot, file.path);
    const stats = await fs.lstat(filePath);
    if (!stats.isFile() || stats.isSymbolicLink() || stats.size !== file.size) {
      throw new Error(`Backup payload metadata verification failed: ${file.path}.`);
    }
    if ((await sha256(filePath)) !== file.sha256) {
      throw new Error(`Backup payload SHA-256 verification failed: ${file.path}.`);
    }
  }
  return manifest;
}

async function stageManifestFiles(backupRoot, destinationRoot, prefix, files) {
  await fs.mkdir(destinationRoot, { recursive: true });
  for (const file of files.filter((entry) => entry.path.startsWith(`${prefix}/`))) {
    const relative = file.path.slice(prefix.length + 1);
    validateRelativePath(relative, "Staged restore path");
    const destination = path.join(destinationRoot, ...relative.split("/"));
    await fs.mkdir(path.dirname(destination), { recursive: true });
    await fs.copyFile(payloadPath(backupRoot, file.path), destination);
    await fs.chmod(destination, file.mode);
    const stats = await fs.lstat(destination);
    if (stats.size !== file.size || (await sha256(destination)) !== file.sha256) {
      throw new Error(`Staged restore verification failed: ${file.path}.`);
    }
  }
}

async function commitRestoreUnits(units, operations) {
  const processed = [];
  try {
    for (const unit of units) {
      unit.hadOriginal = (await pathKind(unit.targetPath)) !== "missing";
      if (unit.hadOriginal) {
        await operations.rename(unit.targetPath, unit.rollbackPath);
        unit.originalMoved = true;
      }
      processed.push(unit);
      if (unit.stagingPath) {
        await operations.rename(unit.stagingPath, unit.targetPath);
        unit.applied = true;
      }
    }
  } catch (error) {
    const rollbackErrors = [];
    for (const unit of [...processed].reverse()) {
      try {
        if (unit.applied && (await pathKind(unit.targetPath)) !== "missing") {
          await operations.rm(unit.targetPath, { recursive: true, force: true });
        }
        if (unit.originalMoved) {
          await operations.rename(unit.rollbackPath, unit.targetPath);
        }
      } catch (rollbackError) {
        rollbackErrors.push(errorMessage(rollbackError));
      }
    }
    if (rollbackErrors.length > 0) {
      throw new Error(
        `Atomic restore failed (${errorMessage(error)}) and automatic rollback also failed: ${rollbackErrors.join(" ")}`
      );
    }
    throw new Error(`Atomic restore failed and original data was restored: ${errorMessage(error)}`);
  }
  await Promise.all(
    units.map((unit) => operations.rm(unit.rollbackPath, { recursive: true, force: true }).catch(() => {}))
  );
}

function assertRestoreSourceOutsideTargets(backupRoot, config) {
  const targets = [
    ...config.profiles.map((profile) => profile.dataDir),
    ...AUDIT_FILES.map((name) => path.join(config.dataDir, name))
  ];
  for (const target of targets) {
    if (pathsOverlap(backupRoot, target) || pathsOverlap(target, backupRoot)) {
      throw new Error(`Backup root overlaps a restore target: ${target}.`);
    }
  }
}

async function restoreGatewayDataBackupUnlocked({
  config: rawConfig,
  backupRoot,
  preRestoreRoot,
  uniqueId = () => randomUUID(),
  operations = fs
}) {
  const resolvedBackupRoot = path.resolve(backupRoot);
  const manifest = await verifyGatewayDataBackup(resolvedBackupRoot);
  const config = normalizeGatewayDataConfig(rawConfig);
  assertRestoreSourceOutsideTargets(resolvedBackupRoot, config);
  const configuredIds = config.profiles.map((profile) => profile.id).sort();
  const backupIds = manifest.profiles.map((profile) => profile.id).sort();
  if (JSON.stringify(configuredIds) !== JSON.stringify(backupIds)) {
    throw new Error("Backup profile ids do not exactly match the configured gateway profiles.");
  }

  const resolvedPreRestoreRoot = path.resolve(preRestoreRoot ?? path.join(path.dirname(resolvedBackupRoot), "pre-restore"));
  if (pathsOverlap(resolvedBackupRoot, resolvedPreRestoreRoot)) {
    throw new Error("Pre-restore backup destination must not be inside the backup being restored.");
  }
  const preRestore = await createGatewayDataBackupUnlocked({
    config,
    destinationRoot: resolvedPreRestoreRoot,
    purpose: "pre-restore"
  });
  const suffix = String(uniqueId()).replace(/[^a-zA-Z0-9_-]/gu, "").slice(0, 12) || "restore";
  const units = [];

  try {
    for (const profile of config.profiles) {
      const parent = path.dirname(profile.dataDir);
      const base = path.basename(profile.dataDir);
      await fs.mkdir(parent, { recursive: true });
      const stagingPath = path.join(parent, `.${base}.forgeos-restore-stage-${suffix}`);
      const rollbackPath = path.join(parent, `.${base}.forgeos-restore-rollback-${suffix}`);
      if ((await pathKind(stagingPath)) !== "missing" || (await pathKind(rollbackPath)) !== "missing") {
        throw new Error(`Restore staging path already exists for profile ${profile.id}.`);
      }
      units.push({ targetPath: profile.dataDir, stagingPath, rollbackPath });
      await stageManifestFiles(resolvedBackupRoot, stagingPath, `profiles/${profile.id}`, manifest.files);
    }
    for (const auditFile of AUDIT_FILES) {
      const targetPath = path.join(config.dataDir, auditFile);
      const rollbackPath = `${targetPath}.forgeos-restore-rollback-${suffix}`;
      const manifestFile = manifest.files.find((file) => file.path === `global/${auditFile}`);
      let stagingPath = null;
      await fs.mkdir(path.dirname(targetPath), { recursive: true });
      if ((await pathKind(rollbackPath)) !== "missing") {
        throw new Error(`Restore rollback path already exists for ${auditFile}.`);
      }
      const unit = { targetPath, stagingPath, rollbackPath };
      units.push(unit);
      if (manifestFile) {
        stagingPath = `${targetPath}.forgeos-restore-stage-${suffix}`;
        unit.stagingPath = stagingPath;
        if ((await pathKind(stagingPath)) !== "missing") {
          throw new Error(`Restore staging path already exists for ${auditFile}.`);
        }
        await fs.copyFile(payloadPath(resolvedBackupRoot, manifestFile.path), stagingPath);
        await fs.chmod(stagingPath, manifestFile.mode);
        if ((await sha256(stagingPath)) !== manifestFile.sha256) {
          throw new Error(`Staged restore verification failed: ${manifestFile.path}.`);
        }
      }
    }
    await commitRestoreUnits(units, operations);
    return { manifest, preRestoreBackupPath: preRestore.backupPath };
  } catch (error) {
    await Promise.all(
      units
        .map((unit) => unit.stagingPath)
        .filter(Boolean)
        .map((candidate) => fs.rm(candidate, { recursive: true, force: true }).catch(() => {}))
    );
    throw new Error(`Restore failed. Pre-restore backup retained at ${preRestore.backupPath}. ${errorMessage(error)}`);
  }
}

export async function restoreGatewayDataBackup(options) {
  const releaseMaintenance = await acquireGatewayDataMaintenance(options?.runtimeStateDir);
  try {
    return await restoreGatewayDataBackupUnlocked(options);
  } finally {
    await releaseMaintenance();
  }
}

function printUsage() {
  console.log("ForgeOS gateway business-data backup commands:");
  console.log(
    "  pnpm gateway:data backup --config <codex-webui.yml> --destination <backup-storage-directory>"
  );
  console.log("  pnpm gateway:data verify --backup <backup-directory>");
  console.log(
    "  pnpm gateway:data restore --config <codex-webui.yml> --backup <backup-directory> [--pre-restore-destination <directory>]"
  );
}

function parseCli(argv) {
  const normalizedArgv = argv[0] === "data" ? argv.slice(1) : argv;
  if ([undefined, "help", "--help", "-h"].includes(normalizedArgv[0])) {
    return { help: true };
  }
  const action = normalizedArgv[0] === "create" ? "backup" : normalizedArgv[0];
  const positional = [];
  const options = {};
  const valueOptions = new Set([
    "--config",
    "--destination",
    "--backup",
    "--pre-restore-destination",
    "--pre-restore-root"
  ]);
  for (let index = 1; index < normalizedArgv.length; index += 1) {
    const argument = normalizedArgv[index];
    if (argument === "--help" || argument === "-h") {
      return { help: true };
    }
    if (valueOptions.has(argument)) {
      const value = normalizedArgv[index + 1];
      if (!value) {
        throw new Error(`Missing value for ${argument}.`);
      }
      options[argument.slice(2)] = value;
      index += 1;
    } else if (argument.startsWith("-")) {
      throw new Error(`Unknown option: ${argument}.`);
    } else {
      positional.push(argument);
    }
  }
  return { action, positional, options, help: false };
}

async function runCli(argv) {
  const parsed = parseCli(argv);
  if (parsed.help) {
    printUsage();
    return;
  }
  if (!new Set(["backup", "verify", "restore"]).has(parsed.action)) {
    throw new Error(`Unknown backup action: ${parsed.action}.`);
  }
  if (parsed.positional.length > 1) {
    throw new Error(`The ${parsed.action} command accepts at most one directory argument.`);
  }
  const legacyTarget = parsed.positional[0];
  const targetOption = parsed.action === "backup" ? parsed.options.destination : parsed.options.backup;
  const target = targetOption ?? legacyTarget;
  if (!target) {
    const requiredOption = parsed.action === "backup" ? "--destination" : "--backup";
    throw new Error(`The ${parsed.action} command requires ${requiredOption}.`);
  }
  const resolvedTarget = path.resolve(target);
  if (parsed.action === "verify") {
    const manifest = await verifyGatewayDataBackup(resolvedTarget);
    console.log(`Verified ${manifest.files.length} files in ${resolvedTarget}.`);
    return;
  }
  const configPath = path.resolve(
    parsed.options.config ?? path.join(os.homedir(), ".codex", "codex-webui.yml")
  );
  const config = await readGatewayDataConfig(configPath);
  if (parsed.action === "backup") {
    const result = await createGatewayDataBackup({ config, destinationRoot: resolvedTarget });
    console.log(`Created verified backup: ${result.backupPath}`);
    return;
  }
  if (parsed.action === "restore") {
    const result = await restoreGatewayDataBackup({
      config,
      backupRoot: resolvedTarget,
      preRestoreRoot: parsed.options["pre-restore-destination"] ?? parsed.options["pre-restore-root"]
    });
    console.log(`Restored verified backup: ${resolvedTarget}`);
    console.log(`Pre-restore backup retained at: ${result.preRestoreBackupPath}`);
    return;
  }
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  runCli(process.argv.slice(2)).catch((error) => {
    console.error(errorMessage(error));
    process.exitCode = 1;
  });
}
