# ForgeOS Python SDK Integration

This package is the first ForgeOS runtime integration layer. It controls
multi-turn Codex threads through the official `openai-codex` Python SDK while
keeping Forge task state outside the Codex runtime.

The integration deliberately does not modify the upstream Codex CLI or
`codex-core`. A thin `forge` command manages durable project/task records;
multi-turn execution remains a Python service/SDK responsibility.

## Administrative CLI

```powershell
forge --workspace D:\work\example init --name Example
forge --workspace D:\work\example task new `
  --title "Feature X" `
  --type FEATURE `
  --objective "Implement feature X" `
  --acceptance "tests pass"
forge --workspace D:\work\example task show FORGE-0001
forge --workspace D:\work\example task list
forge --workspace D:\work\example status
forge --workspace D:\work\example doctor
forge --workspace D:\work\example validate FORGE-0001
forge --workspace D:\work\example task report FORGE-0001
forge --workspace D:\work\example memory new --kind PATTERN --title "Retry" --body "Use bounded retry" --created-by maintainer
forge --workspace D:\work\example memory list --status ACCEPTED
forge --workspace D:\work\example policy check FORGE-0001
forge --workspace D:\work\example budget FORGE-0001
forge --workspace D:\work\example integrity scan
forge --workspace D:\work\example migrate status
forge --workspace D:\work\example recover
forge --workspace D:\work\example release fixtures
forge --workspace D:\work\example release check
forge --workspace D:\work\example audit --event-type task.created --limit 50
forge --workspace D:\work\example policy list
forge --workspace D:\work\example bundle export D:\backup\example-forge.zip
forge --workspace D:\work\restored bundle verify D:\backup\example-forge.zip
forge --workspace D:\work\restored bundle import D:\backup\example-forge.zip
```

Commands emit stable JSON and never run a Codex turn. The generated
`.forge/forge.yaml` is JSON syntax, which is valid YAML 1.2, and all state
writes use same-directory temporary files plus `fsync` and atomic replace.

## Local Web control interface

```powershell
forge --workspace D:\work\example ui
```

ForgeOS prints a token-bearing loopback URL such as:

```text
http://127.0.0.1:8765/?token=<random-session-token>
```

Open that exact URL to initialize a project, create tasks, run or resume Codex,
execute validation, review evidence, accept work, and inspect Audit/Execution
records. Use `--port 0` for an automatically selected port and `--read-only`
for inspection-only Codex turns.

The Developer Preview binds only to `127.0.0.1`, requires a random API token,
sets a restrictive Content Security Policy, caps request bodies, serializes
mutating jobs, and keeps the SDK approval policy at `deny_all`. Job projections
are in memory; authoritative task, audit, ExecutionAttempt/Step, Git, Context,
and validation state stays under `.forge/` and survives a restart.

## Controlled workflow

`ForgeExecutionService` runs or resumes the task's Codex thread through the
public `Thread.turn()`/`TurnHandle.stream()` API. The Control service exposes
bounded progress, steer, and idempotent interrupt while persisting each attempt,
Git baseline/current snapshot, and bounded Context Package. A completed Codex
turn only advances the task to `VALIDATING`; it cannot produce `DONE`.
`ValidationRunner` executes configured argv arrays with `shell=False`, timeout,
and bounded output. ForgeOS captures an immutable pre-execution validation
baseline, classifies L4 regressions, requires a complete six-dimension Review
and criterion-by-criterion L5 Acceptance, then persists a Forge Task Report.
Only this complete evidence chain can transition a task to `DONE`.

N3 adds accepted file-backed Decision/Failure/Pattern/Task memory. Retrieval is
deterministic, accepted-only, secret-redacted, limited to eight records and 16
KiB, and persists selection evidence before adding runtime-data fragments to a
Context Package. Validation failures and completed tasks create DRAFT records;
only a human may accept them.

Minimal ForgePolicy runs before baseline, Codex execution, and validation. It
protects workspace/Git paths and Forge-owned validation argv, and project files
may only add DENY rules. It does not replace Codex Sandbox or Approval and does
not claim to intercept tools inside the Codex Runtime.

Validation checks declare `level` as `L1_BUILD`, `L2_UNIT`, or
`L3_INTEGRATION`; ForgeOS generates L4 from baseline/current comparisons and
L5 from human acceptance evidence. `forge doctor` warns when required Build or
Test command coverage is missing.

## Development

Run the isolated tests without installing the Codex runtime dependency:

```powershell
cd forgeos
python -m pytest
```

For a real run, install the package and use an existing Codex login:

```powershell
python -m pip install -e .
```

```python
from pathlib import Path

from forgeos import CodexSdkGateway, CodexSdkSettings

settings = CodexSdkSettings(workspace=Path.cwd())
with CodexSdkGateway(settings) as codex:
    first = codex.run_turn("Inspect this project and propose a plan.")
    second = codex.run_turn("Continue with the first safe change.", thread_id=first.thread_id)
```

The default approval mode is `deny_all`. ForgeOS must make an explicit policy
decision before introducing any approval path.

## Release candidate verification

Build and inspect both Python distributions from the repository root:

```powershell
python -m pip install build
python -m build forgeos --outdir forgeos/dist
$env:PYTHONPATH = "forgeos/src"
python -m forgeos.release_artifacts --project-root forgeos --dist forgeos/dist --write-checksums
```

Production tags must exactly match `forgeos-v<package-version>`. The release workflow generates
SHA-256 checksums and an SPDX SBOM, records GitHub build-provenance attestations, publishes through
PyPI Trusted Publishing, and attaches release evidence to GitHub. A protected `pypi` environment
with a human approver is required before the first production release.

N4 adds explicit execution-attempt budgets, durable human cancellation,
startup recovery reconciliation, evidence integrity scans, and additive
protocol migrations. Recovery never reruns Codex or validators automatically;
abandoned attempts become `INTERRUPTED` and affected tasks become `BLOCKED` or
`CANCELLED`. Use `forge doctor` and `forge integrity scan` before accepting or
exporting operational evidence.

N5 adds canonical protocol v1 fixtures, verified deterministic bundles,
atomic import into an empty workspace, package/release readiness gates,
bounded cursor-based Audit queries, and local Memory/Policy Operator UX.
Bundle export contains only `.forge` evidence, never repository source,
Git objects, Codex credentials, or SDK login state. Import refuses overwrite
and rebinds only the workspace-specific `project.root` after full hash
verification.
