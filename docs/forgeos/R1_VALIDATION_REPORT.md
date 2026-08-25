# R1 Validation Report

Date: 2026-08-25 (Asia/Shanghai)

## 1. Status

**ForgeOS V1 release candidate: PASS. GitHub distribution: RELEASED. PyPI: DEFERRED.**

PR #1 was reviewed and merged as `0706c26b9100e55c8ba34f1d8715b6997a1ede62`. All 14 ForgeOS CI
checks passed. Tag `forgeos-v0.2.0` points to that merge commit. The public GitHub Release contains
the CI-built wheel, sdist, `SHA256SUMS`, and SPDX SBOM; GitHub provenance and SBOM attestations
verify successfully. V1 intentionally defers PyPI publication.

## 2. Repository baseline

| Field | Result |
| --- | --- |
| Branch | `main` release plus `forgeos/r1-optional-pypi` policy follow-up |
| Candidate commit before review fixes | `e75899defefaf8167ba379b9544f857e013ca0ee` |
| Upstream base | `068c49f075cf287a1fe7d1ee36cf005efac922e7` |
| Upstream | `https://github.com/openai/codex.git` |
| Origin | `https://github.com/Azi9527/ForgeOS.git` |
| Pull request | `https://github.com/Azi9527/ForgeOS/pull/1` (merged) |
| Git identity | Configured locally |
| Git signing | No local signing key/tool configured |
| GitHub CLI | Account `Azi9527` authenticated |
| Local evidence | `.forge/` ignored and excluded from staged content |

## 3. Local verification

| Gate | Result | Evidence |
| --- | --- | --- |
| Ruff lint | PASS | `All checks passed!` |
| Ruff format | PASS | changed Python files formatted |
| Pytest | PASS | 117 tests, including model-input, resume-context and Windows lock regressions |
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

Tagged CI published these release digests:

```text
f93c247da8fa16d8432576acf18f25d4b8d6962ad5f36b2378f674947c318a83  forgeos_harness-0.2.0-py3-none-any.whl
e73fddc640f7930822cb78dc973a42af5ec3fddbf230c862d73f1e6f7449b3e0  forgeos_harness-0.2.0.tar.gz
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
3. GitHub CLI authentication was restored; the repository is public and ForgeOS CI is green.
4. Inherited heavyweight upstream workflows were disabled in the ForgeOS repository by owner
   authorization; ForgeOS CI, CLA, post-merge CI, and dependency services remain enabled.
5. `gpg`, `cosign`, and `syft` are not installed locally. R1 uses GitHub OIDC, Sigstore-backed
   `actions/attest`, and PyPI Trusted Publishing instead of a local private key.
6. PyPI publication was removed from the tagged V1 critical path by product decision. It remains an
   optional manual workflow target for a later distribution phase.
7. The sole modification to an existing upstream-owned file is the registered low-risk
   `.gitignore` patch FUP-0004. No Codex Core, Agent Loop, SDK, Sandbox, Approval, MCP, Cargo, or
   Bazel file is modified.

## 6. Remote completion evidence

- Repository: `https://github.com/Azi9527/ForgeOS` (public).
- PR: `https://github.com/Azi9527/ForgeOS/pull/1` (merged).
- Release: `https://github.com/Azi9527/ForgeOS/releases/tag/forgeos-v0.2.0`.
- Workflow run: `https://github.com/Azi9527/ForgeOS/actions/runs/32804934780`.
- The tagged run's build/verify/attest job passed; the overall run stopped at the subsequently
  deferred PyPI job. The GitHub Release was created from that retained, checksum-verified artifact.
- Remote CI: 12 Python cells plus Operator assets and distribution gate passed.
- Supply chain: SHA256, SPDX SBOM, GitHub build provenance and SBOM attestations verified.
- PyPI/TestPyPI: intentionally not published in V1.
