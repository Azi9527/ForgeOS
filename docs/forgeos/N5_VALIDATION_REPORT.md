# ForgeOS N5 Validation Report

## 1. Result

**PASS — N5 Release Readiness & Operator UX completed on 2026-08-25.**

Upstream base: `openai/codex` `main` at `068c49f075cf287a1fe7d1ee36cf005efac922e7`. Required upstream changes: **None in N5**.

## 2. Automated verification

```text
Ruff format check: PASS
Ruff lint: PASS
Node syntax (app.js + operator.js): PASS
Pytest: PASS — 101 passed
Module size gate: PASS — all Python modules <= 500 lines
Wheel: PASS — 54 entries; all N5 modules, fixtures, manifest and assets present
```

N5 coverage includes canonical fixtures, audit filters/cursors/hard limit, Policy human authority and evidence-preserving retirement, deterministic ZIP metadata, hash verification, duplicate/tamper rejection, atomic import/root rebinding, release reports, CLI and authenticated HTTP APIs.

The built wheel was installed with `--no-deps` into an isolated target. It imported from that target as version `0.2.0` and verified all four bundled fixtures; the installation target was removed afterward.

## 3. Real workspace

```text
Package: 0.2.0
Protocol: v1 current
Release Readiness: 6/6 PASS
Doctor: 12/12 PASS
Release pre-persist integrity: 24 files / 0 issues
Doctor evidence integrity: 24 files / 5 objects / 0 issues
Codex SDK: openai-codex 0.147.0
Codex CLI: detected
```

## 4. Real bundle smoke

The real workspace exported 19 authoritative `.forge` files (35,162 uncompressed bytes), verified every SHA-256 entry, imported into an isolated empty workspace, rebound only `project.root`, and passed Doctor 12/12 after import. The archive and isolated workspace were removed after verification.

## 5. Browser verification

An isolated local UI completed:

```text
Memory DRAFT → human ACCEPTED
Project DENY Policy ACTIVE → RETIRED with evidence retained
Audit filter event_type=policy.retired → matching sequence/payload visible
Release Readiness button → PASS, package 0.2.0
Browser console errors → 0
```

The isolated UI process and workspace were removed. The deliverable browser tab was restored to the real workspace.

## 6. Security and boundary verification

- Import refuses an existing `.forge`, unsafe paths, duplicate entries and altered payloads.
- No archive extraction uses member-provided filesystem paths directly.
- Bundle limits prevent unbounded file count, individual files and total expansion.
- Policy cannot create ALLOW rules or retire built-ins.
- Agent/system identities cannot authorize Memory decisions, Cancellation or Policy lifecycle changes.
- No Codex Core, Sandbox, Approval, MCP, App Server or Agent Loop file changed.

## 7. Exit

N5 is complete. ForgeOS V1 is ready for an explicit **R1 release-candidate workflow** after configuring `origin`, committing the ForgeOS tree, adding CI, choosing release credentials/signing, and creating a tag. Those external repository actions were not inferred or performed.
