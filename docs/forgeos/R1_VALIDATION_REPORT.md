# R1 Validation Report

Date: 2026-08-25 (Asia/Shanghai)

## 1. Status

**Local release candidate: PASS. Remote distribution: BLOCKED ON REVIEW/CI/AUTH.**

The locally rebuilt `forgeos-harness` 0.2.0 wheel and source distribution pass inspection. The
candidate is pushed to the private ForgeOS repository and opened as PR #1. The GitHub CLI
credential expired after the push, the corrected CI run is queued behind inherited upstream Codex
workflows, and no attestation, tag, GitHub Release, TestPyPI upload, or PyPI upload is claimed.

## 2. Repository baseline

| Field | Result |
| --- | --- |
| Branch | `forgeos/r1-v0.2.0` |
| Candidate commit before review fixes | `e75899defefaf8167ba379b9544f857e013ca0ee` |
| Upstream base | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| Upstream | `https://github.com/openai/codex.git` |
| Origin | `https://github.com/Azi9527/ForgeOS.git` |
| Pull request | `https://github.com/Azi9527/ForgeOS/pull/1` |
| Git identity | Configured locally |
| Git signing | No local signing key/tool configured |
| GitHub CLI | Account `Azi9527` was authenticated for setup; credential later expired |
| Local evidence | `.forge/` ignored and excluded from staged content |

## 3. Local verification

| Gate | Result | Evidence |
| --- | --- | --- |
| Ruff lint | PASS | `All checks passed!` |
| Ruff format | PASS | changed Python files formatted |
| Pytest | PASS | 116 tests, including model-input, resume-context and OS permission regressions |
| JavaScript syntax | PASS | `app.js` and `operator.js` |
| YAML parse | PASS | both ForgeOS workflow files parsed locally |
| Wheel build | PASS | `forgeos_harness-0.2.0-py3-none-any.whl` |
| Source build | PASS | `forgeos_harness-0.2.0.tar.gz` |
| Distribution inspection | PASS | version, exact tag, metadata, resources, LICENSE and NOTICE |
| Installed dependency set | PASS | `openai-codex 0.147.0`; `pip check` clean |
| Wheel smoke | PASS | installed `forgeos-harness 0.2.0`; `forge --help` |
| Credential pattern scan | PASS | no known credential/private-key prefix in added lines |
| Forbidden staged paths | PASS | no `.forge/`, `dist/`, wheel, sdist, or `.env` |

## 4. Candidate digests

These local build digests are not public release digests. Tagged CI must reproduce and publish its
own `SHA256SUMS`:

```text
05d4d1d202731e543ab15bae09ad5737a0ce3e0644bf8d52d17fc284196d1216  forgeos_harness-0.2.0-py3-none-any.whl
26a43725f9e2c9aca1164e344c2dbb7eca5d7f2dd7542d69e0c60412a380d5ef  forgeos_harness-0.2.0.tar.gz
```

## 5. Review findings

1. Review found two P0 model-context size defects. They were remediated before release: ForgeOS now
   sends a public SDK `list[TextInput]`, each item is capped at 900 UTF-8 bytes, and the full input
   is capped at 9,000 bytes. Dynamic context is fresh untrusted turn data, mutable workspace rules
   no longer receive developer authority, and volatile Git snapshot IDs are excluded from
   model-visible context. The public Python SDK does not expose Codex Core's internal
   `ContextualUserFragment`; R1 records that boundary instead of modifying Codex Core. Steering
   uses the same 900-byte ceiling, and a task contract that cannot be preserved fails explicitly
   with a terminal failed attempt before any SDK call.
2. The initial downstream import is 19,421 lines across 109 files. This exceeds the repository's
   800-line review guidance and remains an explicit P1 review exception or a stacked-PR rewrite
   decision; history has not been rewritten silently.
3. The GitHub CLI credential expired after PR creation and must be reauthenticated before further
   PR, environment, or release operations.
4. The private repository inherited heavyweight upstream Codex workflows. Canceling active runs or
   disabling those workflows requires explicit owner authorization; ForgeOS CI remains queued.
5. `gpg`, `cosign`, and `syft` are not installed locally. R1 uses GitHub OIDC, Sigstore-backed
   `actions/attest`, and PyPI Trusted Publishing instead of a local private key.
6. PyPI lookup returned no matching published distribution for `forgeos-harness`, but only PyPI can
   confirm name creation/ownership during Trusted Publisher setup.
7. The sole modification to an existing upstream-owned file is the registered low-risk
   `.gitignore` patch FUP-0004. No Codex Core, Agent Loop, SDK, Sandbox, Approval, MCP, Cargo, or
   Bazel file is modified.

## 6. Remote gates still required

- Reauthenticate GitHub CLI so PR labels, checks, environments, and release operations can resume.
- Decide whether the initial-import size finding is an accepted exception or authorize a stacked-PR
  rewrite.
- Decide whether to cancel/disable inherited upstream Codex workflows in the ForgeOS repository.
- Obtain review approval and green 12-cell remote Python matrix.
- Configure protected `testpypi`/`pypi` environments and exact Trusted Publisher identity.
- Run a TestPyPI smoke publication if desired.
- Create and push the annotated tag `forgeos-v0.2.0` only after all gates pass.
- Observe successful GitHub provenance/SBOM attestations, PyPI publish attestations, GitHub Release,
  digest comparison, and clean install of the publicly hosted artifact.

Until these gates pass, R1 is **locally ready but externally incomplete**.
