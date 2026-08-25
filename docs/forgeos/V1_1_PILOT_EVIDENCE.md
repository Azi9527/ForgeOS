# V1.1 Real Project Pilot Evidence

Date: 2026-08-25

Workspace: `D:\codex\ForgeOS`
Task: `FORGE-0003` — `V1.1 只读发布候选审核`

## Safety envelope

- Control server: random-token `127.0.0.1` loopback.
- Codex workspace access: `read_only`.
- Approval policy: `deny_all`.
- Task instruction: no file modification, commit, push, credential access, dependency install or
  release action.
- The operator explicitly authorized sending the bounded task and workspace context to the OpenAI
  Responses API.

## Browser evidence

| Observation | Result |
| --- | --- |
| Real workspace readiness | PASS — 12 Doctor checks |
| Default viewport | `innerWidth=1422`, `document.scrollWidth=1405` |
| Narrow viewport | effective width 433 px, document width 416–417 px |
| REVIEWING guidance | `进行人工 Review` |
| Historical DONE without report | `补全历史任务报告` |
| Browser console warnings/errors | none |

The page was tested through the in-app browser against the real loopback server. Temporary tabs and
listeners were closed after each test session.

## Recovery finding

1. Attempt `attempt-13c06fac-784a-4db2-bb8c-b407cefd04d0` failed when the API stream disconnected.
2. Retry preserved the Thread ID but Codex returned `no rollout found for thread id`.
3. The first fallback correctly hit ForgeOS's Thread-consistency gate instead of silently rebinding.
4. The final implementation carries explicit replacement provenance across the SDK boundary and
   persists `codex.thread.replaced` with reason `rollout_missing`.
5. Attempt `attempt-ba6cc077-da82-472f-9969-17205d6c78e1` continued on replacement Thread
   `01a03768-8d9d-7f32-a671-607cffa28726`, completed read-only, and produced current Validation
   evidence with 122 passing tests before the final response-ordering regression test was added.

Other resume failures are not masked. Unit and execution integration tests cover both the permitted
replacement and the fail-closed path. The final suite contains 123 tests, including chronological
ordering of Execution, Validation, Regression and Task Report evidence so the Operator UI presents
the latest result.

## Lifecycle result

The final bounded attempt `attempt-477cf2ee-7894-4d85-bccd-2f80187aabc8` completed without workspace
writes by Codex. ForgeOS then ran independent Validation and L4 Regression before human authority
advanced the task:

```text
CREATED → IMPLEMENTING → VALIDATING → REVIEWING → ACCEPTING → DONE
```

- Final Validation: `validation-c5376af1-2422-4b59-9f2f-b3003697736f` — PASS, 123 tests.
- Final Regression: `regression-87362460-1b6d-4ff8-9550-4395ffb7ae6b` — PASS.
- Review and Acceptance actor: `Azi9527`.
- Task Report: `task-report-1c8c216e-38cb-4599-8a7e-7d59ca37f2a8`.
- Final Task status: `DONE`, revision 26.

The real browser displayed the newest 123-test Validation, accepted all six Review dimensions and
all four Acceptance criteria, then exposed the final Task Report download action.

## 0.2.1 distribution evidence

```text
a7942f090cebde1bd3e3b2e4c33d5a68bc2cffd7ef8faca4efef40b2575fc098  forgeos_harness-0.2.1-py3-none-any.whl
34d89a7a2b904d17fceb168841e03381a321d87cf108da317d8204dc6d4dbfd4  forgeos_harness-0.2.1.tar.gz
```

`forgeos.release_artifacts` validated tag `forgeos-v0.2.1`, metadata, LICENSE/NOTICE, protocol
fixtures and the required UI assets including `forgeos/web/pilot.js`. These local ignored artifacts
are verification inputs; the GitHub Release workflow will rebuild and attest clean artifacts after
merge and tag.
