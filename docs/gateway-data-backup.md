# Gateway Business-Data Backup and Restore

The Stage 5 baseline is an offline, versioned directory backup for data owned by
the ForgeOS gateway. It is deliberately separate from the managed gateway
binary release state and does not read or modify `gateway-release-state.json`.

## Commands

Stop the gateway before backup or restore so `ui-state.json`, artifact files,
and the signing key cannot change while they are copied:

```bash
forgeos stop
pnpm gateway:data backup --config ~/.codex/codex-webui.yml --destination /secure/forgeos-backups
pnpm gateway:data verify --backup /secure/forgeos-backups/forgeos-gateway-data-v1-<timestamp>-<id>
pnpm gateway:data restore --config ~/.codex/codex-webui.yml --backup /secure/forgeos-backups/forgeos-gateway-data-v1-<timestamp>-<id>
```

The commands can also be run directly with
`node scripts/gateway-data-backup.mjs data <action> ...`. Restore accepts
`--pre-restore-destination <directory>` when the automatic safety copy should
be kept somewhere other than the backup directory's sibling `pre-restore/`
directory.

`backup` creates a child directory named
`forgeos-gateway-data-v1-<timestamp>-<id>`. The directory contains
`manifest.json` and a `data/` payload. `verify` is read-only. `restore` verifies
the complete backup before creating or replacing any gateway data.

## Included Data

The backup includes every regular file beneath each configured profile
`dataDir`. Today that covers, among other profile-owned state:

- `ui-state.json` and its backup, including the project registry, project
  lifecycle records, queues, preferences, and notification configuration;
- `project-artifacts/`, including uploaded project artifacts;
- `artifact-signing.key`, the profile-local ForgeOS trust root required to
  validate restored artifact manifests;
- profile uploads, theme settings, and arena state.

The current and rotated gateway audit logs,
`<dataDir>/audit-log.jsonl{,.1}`, are also included. A project's lifecycle and
artifact manifest are restored from the registry/lifecycle data in
`ui-state.json`; source repositories are not copied.

The artifact signing key is an internal ForgeOS integrity key, not an external
service credential. It is intentionally included so restored artifacts remain
verifiable. Backup directories can nevertheless contain sensitive project
artifacts and uploads and should be protected with restrictive filesystem
permissions and storage encryption appropriate to the deployment.

Before hashing `ui-state.json` and `ui-state.json.bak`, the backup writer parses
their JSON and replaces known external credential fields, currently
`webhookUrl` and `slackWebhookUrl`, with `null`. These endpoints must be entered
again after restore. If either UI-state file cannot be parsed, backup fails
rather than copying a credential-bearing file without inspection.

## Explicit Exclusions

The tool never walks project source directories or any configured allowed
root. It also excludes the entire `CODEX_HOME` ownership domain, including:

- `auth.json` and other account credentials;
- `config.toml`, which can contain or reference MCP and provider credentials;
- `sessions/`, `archived_sessions/`, rollout JSONL files, `state_5.sqlite`, and
  `session_index.jsonl`;
- Codex plugins, skills, memories, and other Codex-managed state.

The launcher YAML file is read only to locate gateway-owned data; it is not
placed in the backup. Runtime PID/log files, managed binary releases, release
switch state, source repositories, and external deployment credentials are
also outside this baseline. If a profile `dataDir` is configured broadly enough
to contain a `CODEX_HOME`, backup fails rather than risk copying credentials.

## Integrity and Restore Semantics

`manifest.json` pins schema version 1 and records every payload path, byte size,
file mode, and SHA-256 digest. Verification rejects unsupported versions,
unknown manifest fields, duplicate or unlisted files, symlinks and special
files, absolute paths, backslashes, drive/ADS separators, `..` traversal, size
mismatches, and digest mismatches. Restore additionally requires the backup's
profile IDs to exactly match the configured profile IDs.

Before restore changes a target, it creates a second, fully verified backup of
the current state with purpose `pre-restore`. The pre-restore destination must
be outside every profile data directory, so the subsequent replacement cannot
delete it. Restore then copies and re-verifies each payload into sibling staging
paths. Each profile directory and audit file is swapped by rename; originals
remain in rollback paths until every replacement succeeds. If a later rename
fails, already replaced targets are rolled back in reverse order. The retained
pre-restore directory is itself a normal verified backup and can be supplied to
`restore` for an operator-requested rollback.

The replacement is atomic per profile directory or audit file. There is no
cross-filesystem transaction spanning custom profile directories on different
volumes, so the reverse-order rollback and retained pre-restore backup provide
the recovery boundary for a multi-profile restore.
