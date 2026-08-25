# ForgeOS Validation Report

Sections 1–7 preserve the original Python SDK vertical-slice and UI-preview baseline. The current N1 completion evidence is recorded in [N1_VALIDATION_REPORT.md](N1_VALIDATION_REPORT.md).

## 1. Scope

Validated on 2026-08-24 against upstream commit `068c49f075cf287a1fe7d1ee36cf005efac922e7` on branch `main`. The slice contains only ForgeOS-owned Python files under `forgeos/` and documentation under `docs/forgeos/`; no Codex-owned Rust, App Server, CLI, SDK, Cargo, Bazel, Sandbox, Approval, MCP, or Agent Loop file was modified.

## 2. Delivered behavior

- Official Codex Python SDK boundary with start/resume/run and safe defaults.
- ForgeProject, ForgeConfig, ForgeTask and evidence domain objects.
- Explicit task state machine with repair budget and fail-closed DONE gate.
- Versioned `.forge/` file protocol, atomic writes, revision checks and concurrent task IDs.
- Append-only, bounded and secret-redacting Audit JSONL.
- ForgeTask to Codex Thread/Turn correlation and bounded execution records.
- Independent command validation using argv, `shell=False`, timeout and output cap.
- Same-thread repair, review evidence and non-agent acceptance.
- One-shot `forge init/status/task new/show/list` administrative CLI.

## 3. Automated checks

| Check | Result |
| --- | --- |
| `python -m pytest` | PASS — 40 passed in 3.52s, 0 skipped |
| `ruff check --no-cache .` | PASS — no lint findings |
| `ruff format --no-cache --check .` | PASS — 19 files formatted |
| Python source import/parse | PASS through the complete test suite |

The suite covers serialization/version rejection, legal and illegal state transitions, evidence gates, repair limits, initialization conflicts, process restart recovery, concurrent ID allocation, stale revisions, path traversal, symbolic-link defense, audit redaction, SDK start/resume normalization, interrupted/failed turns, command timeout, bounded output, shell metacharacter safety, CLI lifecycle, and the complete validation-review-acceptance path.

## 4. Real SDK smoke

The real smoke used the repository's official `sdk/python/src` package and the installed Codex 0.146.1 Windows binary. Settings were:

```text
workspace_access = read_only
approval_policy = deny_all
ephemeral_threads = true
tool calls = explicitly forbidden by developer/user smoke instructions
```

Result:

```text
status = completed
final_response = FORGEOS_SDK_SMOKE_OK
```

The first attempt inside the restricted command sandbox reached the SDK but failed while sending the Responses request. Re-running the identical read-only smoke with explicit network authorization passed. Root cause: execution-environment network boundary, not SDK protocol or ForgeOS integration.

## 5. Security properties verified

- Codex/model identities cannot approve Review or Acceptance.
- Codex turn completion advances only to `VALIDATING`.
- Validation commands never use a command shell.
- No validators means validation fails closed.
- Required validation failure enters bounded `REPAIRING` or `BLOCKED`.
- Project paths reject traversal and symbolic-link boundaries.
- Execution/audit text is bounded and known secret fields are redacted.
- Default SDK approval policy is `deny_all`.

## 6. Known boundaries at the vertical-slice baseline

- This completes the current Python SDK-first vertical slice, not every V1 roadmap item.
- At this earlier baseline, Git evidence, Rules/Context, stream/steer/interrupt and Doctor remained planned. N1 has now delivered those items; typed regression classification and Task Report remain for N2.
- Cross-platform CI has not yet run; the code is written for Python 3.10+ on Windows, Linux and macOS and has one Windows-host test result.
- Full upstream Rust build/test is intentionally not required because there is no upstream Rust patch. It becomes mandatory before the first such patch.

## 7. Local Web Control Developer Preview

Additional automated results:

```text
python -m pytest
48 passed, 0 skipped

ruff check --no-cache .
PASS

ruff format --no-cache --check .
PASS — 23 files formatted

node --check src/forgeos/web/app.js
PASS
```

The HTTP integration suite starts a real ephemeral loopback server and verifies token enforcement, security headers, project initialization, Task creation, background Run, evidence retrieval, Review and Acceptance. Real browser verification covered the initialization page, task dialog, automatic refresh, task detail dashboard and Audit activity. One browser-only asynchronous form-reference defect was found, fixed, regression-checked and reverified; final browser console errors: zero.

The real Control chain used the official repository Python SDK, installed Codex 0.146.1 binary, `read_only` workspace, `deny_all` approval and an ephemeral thread:

```text
job_state = SUCCEEDED
task_status = REVIEWING
response = FORGEOS_CONTROL_SMOKE_OK
validation_passed = true
```

This demonstrates that Codex completion and passing Validation still stop before human Review/Acceptance. A temporary wheel also built successfully and contained `control.py`, `web_server.py`, `web/index.html`, `web/app.js`, and `web/styles.css`.

## 8. N1 completion

N1 completed on 2026-08-24 with 69 automated tests, Ruff/Node/wheel/browser gates, a real `openai-codex 0.147.0` controlled-stream smoke, and 7/7 Doctor checks. See [N1_VALIDATION_REPORT.md](N1_VALIDATION_REPORT.md) for the authoritative result.

## 9. N2 completion

N2 completed on 2026-08-24 with 73 automated tests, typed L1–L5 evidence, baseline-aware L4 Regression, structured Review/Acceptance, a persisted Task Report DONE gate, real SDK workflow smoke, browser and wheel validation. See [N2_VALIDATION_REPORT.md](N2_VALIDATION_REPORT.md).
