# R1 Validation Report

Date: 2026-08-25 (Asia/Shanghai)

## 1. Status

**Local release candidate: PASS. Remote distribution: NOT YET AUTHORIZED/CONFIGURED.**

The repository has a locally verified `forgeos-harness` 0.2.0 wheel and source distribution,
release workflows, tests, checksums, license payload, and clean-install CLI smoke evidence. It does
not yet have a ForgeOS `origin`; the current GitHub CLI credential is invalid; no remote CI,
attestation, tag push, GitHub Release, TestPyPI upload, or PyPI upload has been claimed.

## 2. Repository baseline

| Field | Result |
| --- | --- |
| Branch | `main` before creation of the R1 review branch |
| Upstream base | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| Upstream | `https://github.com/openai/codex.git` |
| Origin | Missing — exact owner/repository URL required |
| Git identity | Configured locally |
| Git signing | No signing key/tool configured |
| GitHub CLI | Account entry exists, credential invalid |
| Local evidence | `.forge/` ignored and excluded from staged content |

## 3. Local verification

| Gate | Result | Evidence |
| --- | --- | --- |
| Ruff lint | PASS | `All checks passed!` |
| Ruff format | PASS | 60 files formatted |
| Pytest | PASS | 104 tests |
| JavaScript syntax | PASS | `app.js` and `operator.js` |
| YAML parse | PASS | Both ForgeOS workflow files parsed locally |
| Wheel build | PASS | `forgeos_harness-0.2.0-py3-none-any.whl` |
| Source build | PASS | `forgeos_harness-0.2.0.tar.gz` |
| Distribution inspection | PASS | version, tag, metadata, resources, LICENSE and NOTICE |
| Installed dependency set | PASS | `openai-codex 0.147.0`; `pip check` clean |
| Wheel smoke | PASS | installed `forgeos-harness 0.2.0`; `forge --help` |
| Credential pattern scan | PASS | no known credential/private-key prefix in added lines |
| Forbidden staged paths | PASS | no `.forge/`, `dist/`, wheel, sdist, or `.env` |

## 4. Candidate digests

These are local build digests and will not be treated as public release digests until the tagged CI
build publishes its own `SHA256SUMS`:

```text
506f10fc963c5a6d901972b4d4361d39dee1d088fab56a4f4f94455b74b15d08  forgeos_harness-0.2.0-py3-none-any.whl
7ae6831367af3474196fd701702c9badae015a93f7d462d229e5e22ca6815a8c  forgeos_harness-0.2.0.tar.gz
```

## 5. Review findings

1. The exact ForgeOS origin cannot be inferred safely. The only configured remote is OpenAI
   `upstream`; pushing ForgeOS branches or tags there is forbidden.
2. The cached GitHub credential for account `Azi9527` is invalid and must be reauthenticated by the
   repository owner before PR or release operations.
3. `gpg`, `cosign`, and `syft` are not installed locally. R1 intentionally uses GitHub OIDC,
   Sigstore-backed `actions/attest`, and PyPI Trusted Publishing instead of a local private key.
4. PyPI lookup returned no matching published distribution for `forgeos-harness`, but only PyPI can
   confirm name creation/ownership during Trusted Publisher setup.
5. The first ForgeOS commit is large (108 files / about 19,306 inserted lines) because M0–N5 work
   accumulated as untracked files on top of the upstream commit. This must be reviewed as an
   initial downstream import; subsequent changes return to the repository's small-change policy.
6. The sole modification to an existing upstream-owned file is the registered low-risk
   `.gitignore` patch FUP-0004. No Codex Core, Agent Loop, SDK, Sandbox, Approval, MCP, Cargo, or
   Bazel file is modified.

## 6. Remote gates still required

- Confirm/create the ForgeOS GitHub repository and configure `origin`.
- Reauthenticate GitHub CLI and push an R1 review branch.
- Obtain review approval and green 12-cell remote Python matrix.
- Configure protected `testpypi`/`pypi` environments and exact Trusted Publisher identity.
- Run a TestPyPI smoke publication if desired.
- Create and push the exact annotated tag `forgeos-v0.2.0` only after review.
- Observe successful GitHub provenance/SBOM attestations, PyPI publish attestations, GitHub Release,
  digest comparison, and clean install of the publicly hosted artifact.

Until these gates pass, R1 is **locally ready but externally incomplete**.
