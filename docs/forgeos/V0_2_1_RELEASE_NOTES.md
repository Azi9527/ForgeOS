# ForgeOS Harness 0.2.1 Release Notes

Status: PREPARED — publish only after PR review, remote CI and merge
Tag: `forgeos-v0.2.1`

## Operator outcome

ForgeOS 0.2.1 is the first V1.1 operator-pilot update. It keeps the existing local, single-Agent,
file-backed architecture and makes the engineering path easier to operate:

- summarize project readiness before an operator starts work;
- show one recommended action for each ForgeTask state;
- export bounded diagnostics and final Task Reports;
- optionally open the exact tokenized loopback URL with `forge ui --open-browser`;
- safely replace a stale Thread ID only when Codex confirms that no rollout exists, with an
  explicit `codex.thread.replaced` Audit event.
- complete the first bounded real-workspace pilot from CREATED through DONE with a generated,
  auditable Task Report.

## Distribution

The release workflow builds wheel and sdist, verifies package version and required assets, emits
SHA-256 checksums and an SPDX SBOM, and publishes build provenance attestations. The required wheel
asset list now includes `forgeos/web/pilot.js`.

GitHub Release remains the required distribution channel. TestPyPI and PyPI remain explicit manual
workflow targets and do not run for a tag push.

## Publish sequence

1. Merge the reviewed V1.1 PR after all required CI checks pass.
2. Create annotated tag `forgeos-v0.2.1` on the merge commit.
3. Push the tag and wait for the `ForgeOS Release` workflow.
4. Verify the GitHub Release contains wheel, sdist, `SHA256SUMS`, SBOM and attestations.
5. Do not dispatch either PyPI target for V1.1 unless separately requested.
