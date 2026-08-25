# ForgeOS V1.1 — Real Project Pilot & Operator UX

Date: 2026-08-25
Status: COMPLETE

## 1. Outcome

V1.1 turns the local V1 developer preview into a guided operator workflow. ForgeOS itself is the
first real-project pilot. The phase does not add a new agent runtime, remote service, database,
Multi-Agent orchestration, or Model Router.

The acceptance path is:

```text
install → launch → readiness → create/select task → recommended action
→ Codex → Validation → Review → Acceptance → export report
```

## 2. Baseline

- Public release: `forgeos-v0.2.0`.
- Runtime: official `openai-codex 0.147.0` Python SDK integration.
- Control surface: token-protected `127.0.0.1` HTTP server and framework-free HTML/CSS/JS.
- Persistence: versioned `.forge/` files; no database.
- Quality baseline: 117 local tests and 14 remote CI checks.
- Upstream patch count: zero active Codex Core patches.

## 3. Work packages

| ID | Scope | Acceptance |
| --- | --- | --- |
| V11-01 | Readiness onboarding | UI summarizes Doctor PASS/WARN/FAIL without repeatedly running diagnostics |
| V11-02 | Recommended next action | Every Task state has one plain-language operator instruction consistent with enabled controls |
| V11-03 | Evidence export | Authenticated JSON downloads exist for bounded diagnostics and final Task Report |
| V11-04 | Launch ergonomics | `forge ui --open-browser` opens the exact tokenized loopback URL |
| V11-05 | Regression coverage | API, CLI, JavaScript syntax, Python tests, and browser flow pass |
| V11-06 | Real-project pilot | ForgeOS workspace loads as healthy and the primary operator path is visually verified |

## 4. Security and size constraints

- The server remains loopback-only and token protected.
- Downloads contain no token, environment variables, credentials, raw model context, or full Git
  diff. Diagnostics are limited to existing bounded status, Doctor checks, and recent job summaries.
- Browser launch is explicit; the default CLI behavior remains headless.
- UI logic is added in a separate small asset instead of growing central orchestration modules.
- No new third-party dependency is introduced.

## 5. Acceptance

1. An uninitialized workspace shows readiness and a clear initialization action.
2. A healthy initialized workspace shows PASS and a recommended first/next action.
3. CREATED, running, VALIDATING, REVIEWING, ACCEPTING, BLOCKED, DONE, FAILED, and CANCELLED states
   have deterministic guidance.
4. A final report and a diagnostic package download as JSON through authenticated routes.
5. The released installation path can launch the UI and find the official Codex SDK/CLI.
6. Full tests, Ruff, format, Node syntax, and browser verification pass with no Codex-owned changes.
