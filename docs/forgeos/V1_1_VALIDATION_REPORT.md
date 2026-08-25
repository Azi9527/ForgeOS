# ForgeOS V1.1 — Real Project Pilot & Operator UX Validation

Date: 2026-08-25
Status: PASS

## 1. Baseline

| Item | Result |
| --- | --- |
| Branch | `forgeos/v1.1-pilot-ux` |
| Baseline commit | `38f60bea9de6be4d15e55ec23593d1b8acd35bcc` |
| Released package | `forgeos-harness 0.2.0` / `forgeos-v0.2.0` |
| Official SDK | `openai-codex 0.147.0` |
| Upstream Codex patches | None |

## 2. Delivered operator path

The local control surface now exposes one compact path:

```text
launch → readiness → create/select Task → recommended next action
→ Codex → Validation → Review → Acceptance → evidence export
```

- Doctor checks are summarized as PASS/WARN/FAIL on initial and initialized workspaces.
- Task guidance covers active Run/Validation and all durable Task states.
- Historical DONE tasks without a Forge Task Report are identified explicitly instead of exposing
  a broken download action.
- Bounded diagnostics and final Task Reports have authenticated JSON export routes.
- `forge ui --open-browser` opens the exact random-token loopback URL; default launch remains
  headless.
- Diagnostics include status, Doctor results and at most 20 job metadata summaries. They exclude
  job results, errors, progress, model output, environment variables and the UI token.

## 3. Automated verification

| Gate | Result |
| --- | --- |
| Python suite | PASS — 123 tests after recovery and response-ordering coverage |
| Ruff | PASS |
| Ruff format check | PASS — 64 files formatted |
| JavaScript syntax | PASS — `operator.js`, `pilot.js`, `app.js` |
| Focused CLI / Control / HTTP tests | PASS — 17 tests |
| Diff whitespace check | PASS |
| Real workspace Doctor | PASS — 12/12 checks |
| Wheel and sdist | PASS — `0.2.1` built locally with `--no-isolation` |
| Wheel contents | PASS — release gate requires `web/pilot.js`, `web/app.js`, and `web/index.html` |

The first isolated build attempt waited while trying to install the already-available Hatchling
backend in a network-restricted environment. It was stopped and repeated with `--no-isolation`;
the local backend completed both distributions successfully. No product test was skipped.

## 4. Real-project browser pilot

ForgeOS itself (`D:\codex\ForgeOS`) was used as the pilot workspace through a real tokenized
loopback server.

- Readiness rendered PASS with all 12 Doctor checks.
- A real REVIEWING task rendered `进行人工 Review` with the six review dimensions.
- A historical DONE task without a report rendered `补全历史任务报告`.
- The diagnostics action completed without browser console errors; the HTTP export contract and
  attachment headers were independently covered by the end-to-end server test.
- Default desktop viewport had no horizontal overflow.
- A narrow effective viewport of 433 px had no horizontal overflow and retained the readiness and
  Task controls.
- The temporary browser tab and loopback server were closed after verification.

The second pilot created real task `FORGE-0003`. A network interruption left a persisted Thread ID
before Codex had created a rollout. The task correctly blocked. V1.1 now starts a replacement only
for the exact `no rollout found for thread id` error and persists a `codex.thread.replaced` event
before continuing. Other resume errors remain failures.

The replacement Thread completed a real Codex turn under `read_only` workspace access and
`deny_all` approval policy. ForgeOS then produced final Validation (123 tests), passing L4
Regression, structured human Review, criterion-level Acceptance and Task Report
`task-report-1c8c216e-38cb-4599-8a7e-7d59ca37f2a8`. The task reached `DONE` at revision 26.
Dedicated evidence is in [V1_1_PILOT_EVIDENCE.md](V1_1_PILOT_EVIDENCE.md).

## 5. Files and ownership

All runtime changes remain under the ForgeOS-owned Python package and documentation:

- `forgeos/src/forgeos/control.py`
- `forgeos/src/forgeos/web_server.py`
- `forgeos/src/forgeos/cli.py`
- `forgeos/src/forgeos/web/`
- `forgeos/tests/`
- `forgeos/README.md`
- `docs/forgeos/`

Codex-owned Rust, App Server, CLI and protocol files were not modified. The upstream patch registry
therefore remains unchanged.

## 6. Release recommendation

This slice is suitable for review as ForgeOS Harness `0.2.1`. The deliberately bounded,
non-destructive real repository task has completed from CREATED through DONE and its generated Task
Report is the release evidence. Remaining release work is limited to PR review, remote CI, merge and
the `forgeos-v0.2.1` GitHub Release. PyPI remains optional and must not block the GitHub Release.
