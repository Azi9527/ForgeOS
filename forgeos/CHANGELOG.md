# Changelog

All notable ForgeOS Harness changes are recorded here. Versions follow the Python package
version in `pyproject.toml` and release tags use `forgeos-v<version>`.

## 0.2.1 — V1.1 operator pilot

- Added guided Doctor readiness, deterministic per-state next actions, bounded diagnostic export,
  Forge Task Report download, and optional exact-URL browser launch.
- Added a real read-only ForgeTask pilot covering Codex, Validation, Review, Acceptance, and final
  report evidence.
- Recover a persisted Thread ID only when Codex explicitly reports that its rollout never existed
  and ForgeOS has no persisted execution history for that Thread; the replacement is narrowly
  authorized and recorded in Audit.
- Added `pilot.js` to both runtime and distribution release gates. PyPI remains an optional manual
  target and does not block GitHub Releases.

## 0.2.0 — V1 release candidate

- Added the ForgeProject, ForgeTask, versioned `.forge` protocol, task state machine, audit log,
  and administrative CLI.
- Integrated persistent Codex Python SDK threads and turns with deny-all approvals by default.
- Added bounded context, rules, Git evidence, validation, regression, review, acceptance, and
  task reports.
- Added accepted-only engineering memory and additive Forge policy.
- Added budgets, cancellation, recovery, integrity scans, migrations, doctor checks, verified
  bundles, stable protocol fixtures, and the local loopback Operator UI.
- Added release gates, cross-platform CI, reproducible wheel/sdist inspection, checksums, SBOM,
  build provenance, and keyless PyPI publication.

This release remains a single-agent local engineering harness. Multi-agent orchestration, model
routing, remote SaaS operation, and database-backed control planes are outside this release.
