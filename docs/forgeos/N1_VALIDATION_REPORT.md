# ForgeOS N1 Validation Report

## 1. Result

**PASS — N1 Controlled Execution & Engineering Evidence completed on 2026-08-24.**

Upstream base is `openai/codex` `main` at `068c49f075cf287a1fe7d1ee36cf005efac922e7`. N1 changed only ForgeOS-owned files under `forgeos/`, `.forge/` protocol state, and `docs/forgeos/`. Required upstream changes: **None in N1**.

## 2. Delivered scope

| Change | Result |
| --- | --- |
| C18 | Versioned, revision-safe `ExecutionAttempt` and `ExecutionStepResult`; startup recovery converts incomplete attempts to `INTERRUPTED` |
| C19 | Official SDK `Thread.turn()` + `TurnHandle.stream()` adapter with allowlisted bounded progress |
| C20 | Idempotent interrupt, bounded steer, one active turn per Task, persisted Thread/Turn correlation and same-thread resume |
| C21 | Read-only Git baseline/current snapshots with HEAD, branch/detached state, changed paths and SHA-256 evidence |
| C22 | Deterministic `.forge/rules/**/*.md` resolver with scope, severity, enforcement and fail-closed conflict handling |
| C23 | Deterministic bounded Context Package with authority, source, hash, byte and truncation metadata |
| C24 | Read-only `forge doctor`, additive Control API, progress/control/evidence UI and page-owned human decision dialog |
| C25 | Recovery/security regression, real SDK, browser, packaging and documentation gates |

## 3. Automated verification

Executed from `D:\codex\ForgeOS`:

```text
python -m ruff format --no-cache --config forgeos\pyproject.toml forgeos
PASS — 35 files unchanged

python -m ruff check --no-cache --config forgeos\pyproject.toml forgeos
PASS

node --check forgeos\src\forgeos\web\app.js
PASS

python -m pytest -q forgeos\tests
PASS — 69 passed
```

Coverage includes attempt revision/terminal/recovery behavior; public SDK stream and same-thread controls; interrupt/revision race; clean, dirty, non-repository and Unicode Git paths; rule ordering/conflicts/symlinks; Context determinism/budgets/redaction/authority; Doctor health/failure/read-only behavior; HTTP token/control routes; custom decision dialog; workflow persistence and restart projection.

## 4. Real official SDK smoke

Runtime: `openai-codex 0.147.0`, ephemeral thread, `read_only`, `deny_all`, tool calls forbidden by the smoke instructions.

```text
status = completed
final_response = N1_SDK_SMOKE_OK.
events = 15
methods = item/agentMessage/delta, item/completed, item/started,
          thread/tokenUsage/updated, turn/completed, turn/started
```

This verifies the real `turn → stream → turn/completed` path rather than only a fake SDK contract.

## 5. Doctor and HTTP result

`forge doctor` and authenticated `GET /api/doctor` both returned `passed=true` with seven PASS checks: workspace, config schema, additive layout, incomplete-attempt recovery, Git, official SDK, and Codex CLI. The repository remained on HEAD `068c49f075cf287a1fe7d1ee36cf005efac922e7`, branch `main`.

## 6. Browser and packaging result

- New local server loaded successfully in the in-app browser.
- Reviewer action opened the page-owned identity/summary dialog; cancel closed it without a state mutation.
- The Task detail rendered ExecutionAttempt, Git Evidence and Context Package sections.
- Browser console errors: zero.
- A temporary wheel built successfully with 28 entries and contained every new N1 runtime module plus `web/app.js`; missing entries: none. The temporary wheel directory was removed after inspection.

## 7. Security and authority conclusions

- Git evidence runs argv commands with `shell=False`, timeout and bounded capture; it never invokes add, commit, reset, checkout, clean, stash or push.
- Task/user content stays at user authority; it is not elevated to developer instructions. Only bounded Forge project/rule/runtime fragments may enter developer authority.
- Raw SDK notification payloads, full environment data and unbounded diff/model/tool content are not persisted or rendered.
- Agent completion still cannot approve Review, Acceptance or `DONE`.
- Interrupt does not delete workspace data, rewrite Git, or automatically retry after restart.

## 8. Exit and next stage

All N1 Exit Gates passed. The next stage is **N2 Validation & Report Completion**: typed L1–L5 checks, baseline-vs-new regression classification, criteria-by-criteria acceptance evidence, structured review checklist and final Forge Task Report. Memory, Multi-Agent, Model Router and remote Web Console remain out of scope.
