# ForgeOS N2 Validation Report

## 1. Result

**PASS — N2 Validation & Report Completion completed on 2026-08-24.**

Upstream base: `openai/codex` `main` at `068c49f075cf287a1fe7d1ee36cf005efac922e7`. Required upstream changes: **None in N2**.

## 2. Delivered evidence chain

```text
Validation baseline
→ Codex execution
→ typed current validation
→ L4 regression comparison
→ repair when required
→ six-dimension Review
→ criterion-level L5 Acceptance
→ persisted Task Report
→ DONE
```

The Task Report includes Task/objective/status, changed files, validation commands, Build/Test/Regression results, Review, Acceptance, repair attempts, risks, technical debt, final Git hashes and start/end commits.

## 3. Automated verification

```text
python -m ruff format --no-cache --check --config forgeos\pyproject.toml forgeos
PASS

python -m ruff check --no-cache --config forgeos\pyproject.toml forgeos
PASS

node --check forgeos\src\forgeos\web\app.js
PASS

python -m pytest -q forgeos\tests
PASS — 73 passed
```

The dedicated N2 vertical test starts from a passing baseline, introduces a required-check regression during the first fake Agent turn, verifies `NEW_REGRESSION` and `REPAIRING`, repairs on the same Task, revalidates, records Review and Acceptance, persists a Task Report, reaches DONE, and verifies restart equality.

All ForgeOS Python implementation modules remain below 500 physical lines; the largest is `execution.py` at 450 lines.

## 4. Real official SDK workflow smoke

An isolated temporary workspace used `openai-codex 0.147.0`, ephemeral thread, `read_only`, `deny_all`, and explicit no-tool instructions.

```text
TASK_STATUS=REVIEWING
SDK_RESPONSE=N2_SDK_WORKFLOW_OK
VALIDATION=True
REGRESSION=True
BASELINE=<persisted validation id>
```

This verifies the real SDK path plus pre-execution baseline, typed L1/L2 commands and L4 comparison. The temporary workspace was removed after the smoke.

## 5. Browser verification

Two local browser scenarios were verified:

1. Main workspace: the six required Review dimensions render with PASS/CONCERN/NOT_APPLICABLE and evidence inputs; cancel causes no mutation.
2. Isolated ACCEPTING fixture: both declared acceptance criteria render as ordered `AC-001`/`AC-002` entries with status and required evidence; cancel causes no mutation.

Typed baseline/current Validation, L4 Regression and Forge Task Report panels rendered. A legacy REVIEWING task without N2 regression evidence shows a disabled “缺少 L4 Regression” indicator and the migration action. Browser console errors: zero. The isolated fixture and server were removed after verification; the main local UI remains running.

## 6. Packaging and Doctor

- Wheel build: PASS; 33 entries.
- Required N2 modules and `web/app.js`: all present; missing entries: none.
- Temporary wheel directory: removed.
- `.forge` layout migration: additive and successful.
- Project validation config now declares required `L1_BUILD` syntax and `L2_UNIT` test checks.
- Doctor: workspace, config, layout, validation coverage, execution recovery, Git, SDK and CLI checks pass.

## 7. Authority and failure behavior

- A boolean Agent claim cannot become typed Validation, Review, Acceptance or DONE evidence.
- Missing baseline, missing L4 link, incomplete checklist, unresolved approved concern, mismatched criterion order, empty criterion evidence, missing L1/L2-or-L3 coverage, failed regression or missing Task Report all fail closed.
- Legacy evidence remains inspectable but is not silently promoted to N2 evidence.
- No Codex-owned Rust/App Server/CLI/SDK/Sandbox/Approval/MCP file changed.

## 8. Exit

All N2 work packages and gates passed. The next recommended stage is N3 Engineering Memory & Policy Foundations, limited to accepted file-backed memory and minimal policy enforcement.
