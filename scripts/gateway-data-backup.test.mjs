import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createGatewayDataBackup as createGatewayDataBackupWithRuntimeGuard,
  restoreGatewayDataBackup as restoreGatewayDataBackupWithRuntimeGuard,
  verifyGatewayDataBackup
} from "./gateway-data-backup.mjs";

function runtimeStateDir(config) {
  return path.join(path.dirname(config.dataDir), "gateway-runtime");
}

function createGatewayDataBackup(options) {
  return createGatewayDataBackupWithRuntimeGuard({
    ...options,
    runtimeStateDir: options.runtimeStateDir ?? runtimeStateDir(options.config)
  });
}

function restoreGatewayDataBackup(options) {
  return restoreGatewayDataBackupWithRuntimeGuard({
    ...options,
    runtimeStateDir: options.runtimeStateDir ?? runtimeStateDir(options.config)
  });
}

function testConfig(sandbox, profileIds = ["default"]) {
  const dataDir = path.join(sandbox, "gateway-data");
  return {
    dataDir,
    codexHome: path.join(sandbox, "codex-home"),
    defaultProfileId: profileIds[0],
    profiles: profileIds.map((id) => ({
      id,
      codexHome: path.join(sandbox, "codex-homes", id),
      dataDir: path.join(dataDir, "profiles", id)
    }))
  };
}

async function writeBusinessFixture(config, profileId, marker) {
  const profile = config.profiles.find((entry) => entry.id === profileId);
  await fs.mkdir(path.join(profile.dataDir, "project-artifacts", "project-hash"), { recursive: true });
  await fs.writeFile(
    path.join(profile.dataDir, "ui-state.json"),
    JSON.stringify({
      marker,
      notifications: {
        settings: {
          webhookUrl: `https://hooks.example.test/${marker}`,
          slackWebhookUrl: `https://hooks.slack.test/${marker}`
        }
      }
    })
  );
  await fs.writeFile(path.join(profile.dataDir, "artifact-signing.key"), `signing-${marker}`);
  await fs.writeFile(
    path.join(profile.dataDir, "project-artifacts", "project-hash", "artifact.bin"),
    `artifact-${marker}`
  );
}

async function readMarker(config, profileId) {
  const profile = config.profiles.find((entry) => entry.id === profileId);
  return JSON.parse(await fs.readFile(path.join(profile.dataDir, "ui-state.json"), "utf8")).marker;
}

test("creates a versioned verified backup, restores it, and retains a usable pre-restore backup", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-success-"));
  try {
    const config = testConfig(sandbox);
    const profile = config.profiles[0];
    await writeBusinessFixture(config, "default", "backup");
    await fs.mkdir(path.join(profile.codexHome, "sessions", "2026", "08", "29"), { recursive: true });
    await fs.writeFile(path.join(profile.codexHome, "auth.json"), "external-token");
    await fs.writeFile(path.join(profile.codexHome, "config.toml"), "mcp_token = 'external'");
    await fs.writeFile(
      path.join(profile.codexHome, "sessions", "2026", "08", "29", "rollout.jsonl"),
      "codex-owned-rollout"
    );
    await fs.mkdir(config.dataDir, { recursive: true });
    await fs.writeFile(path.join(config.dataDir, "audit-log.jsonl"), '{"event":"backup"}\n');

    const created = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      now: () => new Date("2026-08-29T01:02:03.004Z"),
      uniqueId: () => "success"
    });
    assert.match(path.basename(created.backupPath), /^forgeos-gateway-data-v1-/u);
    const manifest = await verifyGatewayDataBackup(created.backupPath);
    assert.equal(manifest.schemaVersion, 1);
    assert.equal(manifest.purpose, "manual");
    assert.ok(manifest.files.some((file) => file.path === "profiles/default/ui-state.json"));
    assert.ok(manifest.files.some((file) => file.path === "profiles/default/artifact-signing.key"));
    assert.ok(manifest.files.some((file) => file.path.endsWith("project-artifacts/project-hash/artifact.bin")));
    assert.ok(manifest.files.some((file) => file.path === "global/audit-log.jsonl"));
    assert.ok(manifest.files.every((file) => !/auth\.json|config\.toml|sessions|rollout/iu.test(file.path)));
    const archivedUiState = JSON.parse(
      await fs.readFile(path.join(created.backupPath, "data", "profiles", "default", "ui-state.json"), "utf8")
    );
    assert.equal(archivedUiState.notifications.settings.webhookUrl, null);
    assert.equal(archivedUiState.notifications.settings.slackWebhookUrl, null);
    assert.ok(!JSON.stringify(archivedUiState).includes("hooks.example.test"));

    await writeBusinessFixture(config, "default", "live-before-restore");
    await fs.writeFile(path.join(config.dataDir, "audit-log.jsonl"), '{"event":"live"}\n');
    await fs.writeFile(path.join(profile.codexHome, "config.toml"), "mcp_token = 'still-external'");

    const restored = await restoreGatewayDataBackup({
      config,
      backupRoot: created.backupPath,
      preRestoreRoot: path.join(sandbox, "pre-restore"),
      uniqueId: () => "restore-success"
    });
    assert.equal(await readMarker(config, "default"), "backup");
    assert.equal(await fs.readFile(path.join(profile.dataDir, "artifact-signing.key"), "utf8"), "signing-backup");
    assert.equal(
      JSON.parse(await fs.readFile(path.join(profile.dataDir, "ui-state.json"), "utf8")).notifications.settings.webhookUrl,
      null
    );
    assert.equal(await fs.readFile(path.join(config.dataDir, "audit-log.jsonl"), "utf8"), '{"event":"backup"}\n');
    assert.equal(await fs.readFile(path.join(profile.codexHome, "config.toml"), "utf8"), "mcp_token = 'still-external'");

    const preRestoreManifest = await verifyGatewayDataBackup(restored.preRestoreBackupPath);
    assert.equal(preRestoreManifest.purpose, "pre-restore");
    await restoreGatewayDataBackup({
      config,
      backupRoot: restored.preRestoreBackupPath,
      preRestoreRoot: path.join(sandbox, "rollback-safety-copy"),
      uniqueId: () => "manual-rollback"
    });
    assert.equal(await readMarker(config, "default"), "live-before-restore");
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("rejects a payload whose contents no longer match its SHA-256", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-tamper-"));
  try {
    const config = testConfig(sandbox);
    await writeBusinessFixture(config, "default", "verified");
    const created = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      uniqueId: () => "tamper"
    });
    await fs.writeFile(path.join(created.backupPath, "data", "profiles", "default", "ui-state.json"), "tampered");
    await fs.writeFile(path.join(config.profiles[0].dataDir, "ui-state.json"), "live-unchanged");

    await assert.rejects(() => verifyGatewayDataBackup(created.backupPath), /metadata verification|SHA-256/u);
    await assert.rejects(
      () => restoreGatewayDataBackup({ config, backupRoot: created.backupPath }),
      /metadata verification|SHA-256/u
    );
    assert.equal(await fs.readFile(path.join(config.profiles[0].dataDir, "ui-state.json"), "utf8"), "live-unchanged");
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("rejects path traversal and incompatible manifest versions before reading payload paths", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-manifest-"));
  try {
    const config = testConfig(sandbox);
    await writeBusinessFixture(config, "default", "manifest");
    const traversal = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      uniqueId: () => "traversal"
    });
    const traversalManifestPath = path.join(traversal.backupPath, "manifest.json");
    const traversalManifest = JSON.parse(await fs.readFile(traversalManifestPath, "utf8"));
    traversalManifest.files[0].path = "profiles/default/../../outside";
    await fs.writeFile(traversalManifestPath, JSON.stringify(traversalManifest));
    await assert.rejects(() => verifyGatewayDataBackup(traversal.backupPath), /path traversal/u);

    const incompatible = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      uniqueId: () => "incompatible"
    });
    const incompatibleManifestPath = path.join(incompatible.backupPath, "manifest.json");
    const incompatibleManifest = JSON.parse(await fs.readFile(incompatibleManifestPath, "utf8"));
    incompatibleManifest.schemaVersion = 2;
    await fs.writeFile(incompatibleManifestPath, JSON.stringify(incompatibleManifest));
    await assert.rejects(() => verifyGatewayDataBackup(incompatible.backupPath), /Unsupported backup schema version: 2/u);
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("refuses backup and restore while the gateway is active", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-active-"));
  try {
    const config = testConfig(sandbox);
    const activeRuntime = path.join(sandbox, "active-runtime");
    await writeBusinessFixture(config, "default", "active");
    await fs.mkdir(activeRuntime, { recursive: true });
    await fs.writeFile(path.join(activeRuntime, "server.pid"), String(process.pid));

    await assert.rejects(
      () =>
        createGatewayDataBackup({
          config,
          destinationRoot: path.join(sandbox, "backups"),
          runtimeStateDir: activeRuntime
        }),
      /Stop the ForgeOS gateway/u
    );
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("refuses to restore from a backup nested in a restore target", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-overlap-"));
  try {
    const config = testConfig(sandbox);
    await writeBusinessFixture(config, "default", "live");
    const created = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      uniqueId: () => "outside"
    });
    const nestedBackup = path.join(config.profiles[0].dataDir, "nested-backup");
    await fs.cp(created.backupPath, nestedBackup, { recursive: true });

    await assert.rejects(
      () => restoreGatewayDataBackup({ config, backupRoot: nestedBackup }),
      /Backup root overlaps a restore target/u
    );
    assert.equal(await readMarker(config, "default"), "live");
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});

test("rolls every replaced profile back when a later atomic replacement fails", async () => {
  const sandbox = await fs.mkdtemp(path.join(os.tmpdir(), "forgeos-data-backup-rollback-"));
  try {
    const config = testConfig(sandbox, ["alpha", "beta"]);
    await writeBusinessFixture(config, "alpha", "backup-alpha");
    await writeBusinessFixture(config, "beta", "backup-beta");
    const created = await createGatewayDataBackup({
      config,
      destinationRoot: path.join(sandbox, "backups"),
      uniqueId: () => "rollback-source"
    });
    await writeBusinessFixture(config, "alpha", "live-alpha");
    await writeBusinessFixture(config, "beta", "live-beta");

    const betaTarget = config.profiles.find((profile) => profile.id === "beta").dataDir;
    let injected = false;
    const operations = {
      rename: async (source, destination) => {
        if (!injected && destination === betaTarget && source.includes("forgeos-restore-stage")) {
          injected = true;
          throw new Error("injected replacement failure");
        }
        return fs.rename(source, destination);
      },
      rm: (...args) => fs.rm(...args)
    };

    await assert.rejects(
      () =>
        restoreGatewayDataBackup({
          config,
          backupRoot: created.backupPath,
          preRestoreRoot: path.join(sandbox, "pre-restore"),
          uniqueId: () => "rollback-failure",
          operations
        }),
      /original data was restored: injected replacement failure/u
    );
    assert.equal(await readMarker(config, "alpha"), "live-alpha");
    assert.equal(await readMarker(config, "beta"), "live-beta");
    const retained = await fs.readdir(path.join(sandbox, "pre-restore"));
    assert.equal(retained.length, 1);
    assert.equal((await verifyGatewayDataBackup(path.join(sandbox, "pre-restore", retained[0]))).purpose, "pre-restore");
  } finally {
    await fs.rm(sandbox, { recursive: true, force: true });
  }
});
