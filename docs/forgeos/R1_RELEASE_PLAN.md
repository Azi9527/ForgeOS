# R1 — V1 Release Candidate & Distribution Plan

## 1. Outcome

R1 turns the completed local ForgeOS V1 harness into a reviewable and verifiable Python release.
It does not add runtime features. The release unit is `forgeos-harness`; the upstream Codex source
remains the base platform and `openai-codex>=0.146,<0.148` remains a runtime dependency.

## 2. Release invariants

1. `.forge/` operational evidence is never committed or packaged.
2. `pyproject.toml`, `forgeos.release.PACKAGE_VERSION`, and `release_manifest.json` have one version.
3. A production tag is exactly `forgeos-v<version>` and points to the reviewed release commit.
4. CI passes on Windows, Linux, and macOS with Python 3.10, 3.11, 3.12, and 3.13.
5. The wheel contains protocol fixtures, Operator assets, Apache-2.0 `LICENSE`, and `NOTICE`.
6. A release publishes the same CI-built wheel/sdist that were checksummed and attested.
7. Tagged V1 releases publish to GitHub only; PyPI is an optional manual target.
8. If PyPI is enabled later, credentials must be short-lived OIDC credentials.

## 3. Work breakdown

| Task | Scope | Files | Acceptance | Risk |
| --- | --- | --- | --- | --- |
| R1-00 Baseline | Record remote, branch, commit, identity, tools and dirty state | Git evidence, validation report | `upstream` preserved; missing `origin` explicit; `.forge/` excluded | Low |
| R1-01 Package metadata | License files, classifiers, changelog and security policy | `forgeos/pyproject.toml`, package docs | wheel/sdist contain license and notice; metadata parses | Low |
| R1-02 Distribution gate | Inspect filenames, versions, assets, metadata, licenses and hashes | `release_artifacts.py`, tests | malformed tag/artifact fails; `SHA256SUMS` deterministic | Medium |
| R1-03 CI matrix | Cross-platform lint, format and tests; package gate | `forgeos-ci.yml` | 12 Python jobs, JS checks and distribution build pass remotely | Medium: runner differences |
| R1-04 Supply chain | SPDX SBOM, provenance, optional Trusted Publishing, release assets | `forgeos-release.yml` | evidence artifact generated; optional OIDC publication gated | Medium |
| R1-05 Review and commit | Review only ForgeOS files plus registered ignore patch | Git commit/PR | no `.forge/`; no Codex Core change; review findings resolved | Medium |
| R1-06 Origin and PR | Configure ForgeOS-owned origin, push branch, open review | GitHub repository | remote URL confirmed; PR CI green | High: owner authorization |
| R1-07 Tag and publish | Create version tag, publish and verify | GitHub | GitHub Release files, digests, SBOM and attestations match | High: irreversible public release |

## 4. CI design

`forgeos-ci.yml` runs on ForgeOS path changes and has three independent gates:

- `python-matrix`: 3 operating systems × 4 Python versions; install, Ruff, format, pytest.
- `static-assets`: Node syntax checks for the two Operator JavaScript modules.
- `distribution`: clean wheel/sdist build, content inspection, checksum generation, short-lived
  candidate artifact retention.

`forgeos-release.yml` is a separate least-privilege workflow. A tag build must pass exact-version
validation before evidence creation. `actions/attest` receives only `id-token`, `attestations`, and
read permissions in the build job. GitHub Release gets only `contents: write` after the build
succeeds. Optional manually requested PyPI publication gets only `id-token: write` and never blocks
a tagged GitHub Release.

## 5. Distribution and signing

The workflow creates:

```text
forgeos_harness-<version>-py3-none-any.whl
forgeos_harness-<version>.tar.gz
SHA256SUMS
forgeos-harness.spdx.json
GitHub build provenance attestations
Optional PyPI publish attestations
```

PyPI's official action generates keyless publish attestations by default when invoked through a
Trusted Publisher. GitHub provenance and SBOM attestations are independently verifiable with
`gh attestation verify`. This avoids local GPG key distribution and long-lived PyPI API tokens.

## 6. Owner-controlled setup

Before a public tag, the repository owner must:

1. Create or identify the ForgeOS GitHub repository and provide its exact clone URL.
2. Configure `origin` while retaining `upstream=https://github.com/openai/codex.git`.
3. Restore `gh auth` with access to that repository.
4. Confirm GitHub Actions can create attestations and release assets.
5. Configure a private security-reporting contact.

PyPI setup is deferred in V1. If enabled later, register the exact Trusted Publisher identity for
`forgeos-release.yml` and the `pypi` environment before manually selecting that target.

## 7. Stop conditions

Do not infer an origin URL, overwrite Git history, create a public package, or create a production
tag without the exact repository and release ownership. A local passing build is not evidence that
remote CI or GitHub attestations succeeded.
