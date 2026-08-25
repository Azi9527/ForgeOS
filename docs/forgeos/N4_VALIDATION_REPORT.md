# ForgeOS N4 Validation Report

## 1. Result

**PASS — N4 Workflow Recovery & Operational Hardening completed on 2026-08-25.**

Upstream base: `openai/codex` `main` at `068c49f075cf287a1fe7d1ee36cf005efac922e7`. Required upstream changes: **None in N4**.

## 2. Delivered operational chain

```text
Budget PASS → Policy PASS → baseline → Codex → Validation/Regression
Budget exhausted → persisted evidence → BLOCKED before external work

Cancellation REQUESTED → interrupt/safe boundary → APPLIED → CANCELLED
Abandoned Attempt → INTERRUPTED → Task BLOCKED/CANCELLED → Recovery Report
```

## 3. Automated verification

```text
python -m ruff format --no-cache --check --config forgeos\pyproject.toml forgeos
PASS

python -m ruff check --no-cache --config forgeos\pyproject.toml forgeos
PASS

node --check forgeos\src\forgeos\web\app.js
PASS

python -m pytest -q forgeos\tests
PASS — 92 passed
```

N4 tests cover exhaustion before baseline/Codex, durable/idempotent human cancellation, pre-execution cancellation, abandoned Attempt recovery, pending cancellation after crash, Memory hash tampering, broken Task Report link, additive/idempotent/future-version migration, CLI, Control facade and authenticated HTTP API.

## 4. Real workspace migration and integrity

```text
Migration: 0 → 1, additive manifest only
Migration status after apply: required=false
Integrity: 16 files / 5 objects / 0 issues / PASS
Doctor: 11/11 PASS
```

No Task, Validation, Memory, Audit or Git history was rewritten.

## 5. Real official SDK smoke

An isolated temporary workspace used installed `openai-codex 0.147.0`, `read_only`, `deny_all`, attempt limit 2 and typed L1/L2 checks.

```text
TASK_STATUS=REVIEWING
SDK_RESPONSE=N4_SDK_OPERATIONAL_OK
BUDGET_PASS=True
ATTEMPTS_USED=1
ATTEMPTS_REMAINING=1
VALIDATION=True
REGRESSION=True
INTEGRITY=True
INTEGRITY_ISSUES=0
```

The temporary workspace and smoke script were removed.

## 6. Packaging and UI

- Wheel PASS with 42 entries; Budget/Recovery/Integrity/Migration/Operations modules and Web assets are present, missing entries none.
- Local UI renders N4 Operations status, Task Budget, Cancellation/Recovery and Integrity evidence.
- Human cancellation uses the existing decision dialog; no browser prompt or direct status mutation was added.
- Browser verification confirmed that dismissing the cancellation dialog leaves `FORGE-0001` in `REVIEWING`; no cancellation request was persisted accidentally.

## 7. Security and boundaries

- Recovery never reruns a model or command automatically.
- Cancellation does not erase evidence and cannot be authorized by Agent/system identities.
- Integrity errors are observable and fail the report; migration refuses future protocol versions.
- ForgeOS does not replace Codex Sandbox/Approval or claim process-level control it does not have.
- No database, daemon fleet, remote service, new Agent runtime or upstream patch was introduced.

## 8. Exit

All N4 work packages passed. Recommended next stage: N5 Release Readiness & Operator UX.
