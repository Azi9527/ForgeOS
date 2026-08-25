# ForgeOS Local Web Control Developer Preview

## 1. Purpose

This is a thin, local interface over the Python SDK-first ForgeOS control layer. It is not a separate Agent runtime and is not a remote Web Console or SaaS platform.

```text
Browser on 127.0.0.1
  → token-protected Forge HTTP API
  → ForgeControlService
  → ForgeService / Workflow / Validation
  → official Codex Python SDK
  → Codex App Server runtime
```

## 2. Start

From an installed editable package:

```powershell
python -m pip install -e D:\codex\ForgeOS\forgeos
forge --workspace D:\work\my-project ui
```

The command prints a random token URL. Open the exact URL; a URL without the token receives HTTP 403.

Options:

```text
--port 8765       fixed loopback port
--port 0          automatically select a free port
--codex-bin PATH  explicit Codex binary
--read-only       force Codex threads to read-only workspace access
```

The normal developer UI uses `workspace_write` so Codex can implement work, while SDK approval remains `deny_all`.

## 3. UI capabilities

- Initialize `.forge/` with an argv-based validation check.
- Create and list ForgeTask records.
- Inspect objective, acceptance criteria, Thread/Turn correlation and revision.
- Submit Codex Run/Resume as a background job.
- Observe bounded SDK progress, steer an active turn, or request an idempotent interrupt.
- Retry interrupted execution on the same Thread.
- Run or retry independent Validation.
- Inspect typed baseline/current Validation and L4 regression classification.
- Approve/reject Review with a named non-agent reviewer and six-dimension checklist.
- Accept completed work criterion-by-criterion with a named non-agent authority.
- Inspect the final persisted Forge Task Report after DONE.
- Inspect persistent ExecutionAttempt/Step, Git baseline/current, Context Package, Audit and Validation evidence.
- Use a page-owned reviewer/acceptor dialog; the UI does not depend on native `prompt()` or a hard-coded authority.

## 4. HTTP API

Every `/api/*` request requires `X-ForgeOS-Token`.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/status` | Project/runtime status |
| GET | `/api/doctor` | Read-only environment and recovery diagnostics |
| GET | `/api/diagnostics/export` | Bounded status, readiness and recent-job metadata download |
| GET | `/api/tasks/{task_id}/report/export` | Final Forge Task Report JSON download |
| POST | `/api/project/init` | Initialize ForgeProject and validation checks |
| GET/POST | `/api/tasks` | List/create tasks |
| GET | `/api/tasks/{id}` | Task plus Audit/Execution/Validation/Job evidence |
| GET | `/api/tasks/{id}/report` | Latest persisted Forge Task Report |
| POST | `/api/tasks/{id}/run` | Queue Codex run/resume |
| POST | `/api/tasks/{id}/interrupt` | Interrupt the active Codex turn idempotently |
| POST | `/api/tasks/{id}/steer` | Send bounded guidance to the active turn |
| POST | `/api/tasks/{id}/validate` | Queue independent Validation |
| POST | `/api/tasks/{id}/review` | Apply named Review evidence |
| POST | `/api/tasks/{id}/accept` | Apply named Acceptance evidence |
| GET | `/api/jobs` | Recent control jobs |
| GET | `/api/jobs/{id}` | One job projection |
| GET | `/api/audit` | Append-only Audit projection |

## 5. Security model

- Bind is hard-limited to `127.0.0.1`; `0.0.0.0` and remote interfaces are rejected.
- A 256-bit random session token protects the document and API.
- No CORS headers are emitted; API mutation requires JSON and the custom token header.
- Content Security Policy allows scripts/styles/connections only from the same origin.
- Request bodies are capped at 1 MiB and error messages at 2,000 characters.
- One worker serializes state-changing background jobs; duplicate active jobs for one Task are rejected.
- The browser never receives authority to set Task status directly.
- Agent, Codex and model identities remain forbidden as Review/Acceptance authorities.
- Validation uses argv with `shell=False`, timeout and bounded output.

## 6. Persistence and recovery

Job status is an in-memory convenience projection and resets when the UI process restarts. Authoritative state does not depend on it: ForgeTask, Audit, ExecutionAttempt/Step, Git, Context and Validation records remain versioned under `.forge/`. Startup marks any non-terminal persisted attempt as `INTERRUPTED` instead of inventing success or automatically rerunning it; a resumable Task retains its Codex Thread ID.

## 7. Current limits

- Polling updates every 1.8 seconds; SDK events are projected as bounded progress rather than transported to the browser as raw notifications.
- Legacy REVIEWING tasks without linked N2 regression evidence must be returned for one repair/run migration; old DONE records remain readable and are not rewritten.
- The V1 preview is local single-user only; remote bind, login/IAM and deployment are intentionally absent.
