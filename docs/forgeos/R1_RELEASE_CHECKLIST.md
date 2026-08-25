# R1 Release Checklist

## Candidate commit

- [x] `git status --short` contains no `.forge/`, credentials, build output, or unrelated files.
- [x] `upstream` is the official OpenAI Codex repository and `origin` is the confirmed ForgeOS repo.
- [x] Package version, runtime constant, manifest, changelog, and tag agree.
- [x] Ruff check and format check pass.
- [x] All ForgeOS tests pass on the local supported Python baseline (117 tests).
- [x] JavaScript syntax checks pass.
- [x] Wheel and sdist pass `forgeos.release_artifacts` and `SHA256SUMS` is generated.
- [x] Diff review confirms no Codex Core/SDK/Sandbox/Approval weakening.
- [x] Release commit is reviewed through PR #1 and the remote CI matrix is green.

## Repository configuration

- [ ] Default branch protection requires `ForgeOS CI` jobs.
- [ ] Release workflow changes require owner review.
- [x] GitHub artifact attestations are supported by the public repository.
- [ ] Optional future PyPI publishing uses an exact Trusted Publisher and protected environment.

## Production release

- [x] Create annotated tag `forgeos-v0.2.0` on the reviewed commit.
- [x] Push the tag to `origin`; never push ForgeOS tags to `upstream`.
- [x] Confirm GitHub Release assets match `SHA256SUMS`.
- [x] Verify artifacts: `gh attestation verify <artifact> -R <owner>/<repo>`.
- [x] Install the GitHub Release wheel in a clean Python 3.10 environment, run `pip check`, and run `forge --help`.
- [x] Record release URL, tag SHA, workflow run and hashes; PyPI is deferred.

## Rollback policy

Public tags, release assets, and attestations are treated as immutable. If a release is defective,
document the reason and issue a new patch version. Do not move or reuse a production tag and do not
replace distribution files under an existing version.
