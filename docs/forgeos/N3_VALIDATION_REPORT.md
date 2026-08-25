# ForgeOS N3 Validation Report

## 1. Result

**PASS — N3 Engineering Memory & Policy Foundations completed on 2026-08-24.**

Upstream base: `openai/codex` `main` at `068c49f075cf287a1fe7d1ee36cf005efac922e7`. Required upstream changes: **None in N3**.

## 2. Delivered chain

```text
Memory candidate → DRAFT → human decision → ACCEPTED-only selection
→ deterministic bounded Context injection → persisted selection evidence

Task + validation plan → Policy Evaluation
→ PASS before baseline/execution/validation
or DENY without external execution
```

Validation failures create linked Failure drafts; accepted Tasks create linked Task drafts. Neither is trusted until a human accepts it.

## 3. Automated verification

```text
python -m ruff format --no-cache --check --config forgeos\pyproject.toml forgeos
PASS

python -m ruff check --no-cache --config forgeos\pyproject.toml forgeos
PASS

node --check forgeos\src\forgeos\web\app.js
PASS

python -m pytest -q forgeos\tests
PASS — 81 passed
```

Coverage includes human authority, stale revision, restart round-trip, supersede provenance, accepted-only retrieval, deterministic rank, 8-record/16-KiB caps, Context authority, secret redaction, `.git` and workspace boundaries, destructive validation commands, additive project DENY, invalid ALLOW fail-closed, automatic Failure/Task drafts, CLI, Control API and authenticated HTTP API.

## 4. Product and protocol verification

- CLI: `memory new/list/show/accept/reject` and `policy check` use the same services as the control plane.
- HTTP: token-protected loopback endpoints create/list/decide Memory and evaluate Policy.
- UI: Task detail renders latest Memory Selection, related records and Policy Evaluation.
- Doctor: additive N3 layout plus all Memory hashes and Policy schemas are checked.
- Packaging: wheel PASS with 36 entries; Memory/Policy modules and Web assets are present, missing entries none.
- Doctor: 9/9 checks PASS in the real workspace, including `memory_policy` and validation coverage.

## 5. Real official SDK smoke

An isolated temporary workspace used installed `openai-codex 0.147.0`, `read_only`, `deny_all`, two passing typed validation checks and one human-accepted Pattern Memory.

```text
TASK_STATUS=REVIEWING
SDK_RESPONSE=N3_SDK_MEMORY_OK
MEMORY_FRAGMENTS=1
MEMORY_SELECTION=memory-selection-6f5e8bac4648245486f8b756
POLICY_PASS=True
VALIDATION=True
REGRESSION=True
```

The fixture verifies the real SDK boundary, accepted Memory selection and injection, pre-execution Policy, baseline/current Validation and L4 Regression. Its temporary workspace and smoke script were removed.

## 6. Security and authority

- No Memory can be selected before human acceptance.
- Agent/model identities cannot decide Memory.
- Injected Memory is runtime evidence, not developer authority, and is bounded/redacted.
- Project Policy can only add DENY; it cannot weaken built-ins or Codex security.
- ForgePolicy scope is honest: it controls Forge-owned Task paths and validator argv, while Codex tool execution remains Codex-owned.
- No shell execution, Git mutation, remote service, database, vector store or upstream change was introduced.

## 7. Exit

N3 requirements and quality gates passed. Recommended next stage: N4 Workflow Recovery & Operational Hardening.
