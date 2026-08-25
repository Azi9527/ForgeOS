# Security Policy

## Supported version

Security fixes are prepared for the latest published `forgeos-harness` version. Until the first
public release, the current release-candidate branch is the supported line.

## Reporting

Do not open a public issue containing credentials, tokens, private source, or exploit details.
Use the private security-advisory feature of the configured ForgeOS `origin` repository. The
repository owner must configure a security contact before the first public release.

## Release security

- PyPI publishing uses GitHub Actions Trusted Publishing with short-lived OIDC credentials.
- The `pypi` GitHub environment must require a human approver.
- The release workflow emits SHA-256 checksums, an SPDX JSON SBOM, GitHub build provenance, and
  PyPI's keyless publish attestations.
- `.forge/` is local operational evidence and is excluded from source control and distributions.
- A release must never be produced from an unreviewed or dirty worktree.
