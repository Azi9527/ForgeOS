# R1 Release Checklist

## Candidate commit

- [ ] `git status --short` contains no `.forge/`, credentials, build output, or unrelated files.
- [ ] `upstream` is the official OpenAI Codex repository and `origin` is the confirmed ForgeOS repo.
- [ ] Package version, runtime constant, manifest, changelog, and tag agree.
- [ ] Ruff check and format check pass.
- [ ] All ForgeOS tests pass on the local supported Python baseline.
- [ ] JavaScript syntax checks pass.
- [ ] Wheel and sdist pass `forgeos.release_artifacts` and `SHA256SUMS` is generated.
- [ ] Diff review confirms no Codex Core/SDK/Sandbox/Approval weakening.
- [ ] Release commit is reviewed through a pull request and remote CI matrix is green.

## Repository configuration

- [ ] Default branch protection requires `ForgeOS CI` jobs.
- [ ] Release workflow changes require owner review.
- [ ] `pypi` environment has required reviewers and blocks self-approval where supported.
- [ ] `testpypi` and `pypi` Trusted Publishers reference `forgeos-release.yml` exactly.
- [ ] PyPI project/package ownership and security contact are confirmed.
- [ ] GitHub artifact attestations are supported by the repository visibility/plan.

## Production release

- [ ] Create annotated tag `forgeos-v<version>` on the reviewed commit.
- [ ] Push the tag to `origin`; never push ForgeOS tags to `upstream`.
- [ ] Approve the `pypi` environment after inspecting the workflow commit and build output.
- [ ] Confirm wheel and sdist on PyPI have provenance/attestations.
- [ ] Confirm GitHub Release assets match `SHA256SUMS`.
- [ ] Verify artifacts: `gh attestation verify <artifact> -R <owner>/<repo>`.
- [ ] Install the published wheel in a clean Python 3.10 environment and run `forge --help`.
- [ ] Record release URL, PyPI URL, tag SHA, workflow run, hashes, and smoke-test result.

## Rollback policy

Published PyPI versions and public attestations are immutable. If a release is defective, yank the
version, document the reason, and issue a new patch version. Do not move or reuse a published
production tag and do not replace distribution files under an existing version.
