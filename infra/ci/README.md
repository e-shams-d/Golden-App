# Provider-neutral CI contract

This contract stays provider-neutral. Any adapter must execute it without weakening
or skipping a failing step.

## Current adapter

GitHub Actions, in `.github/workflows/m1-verify.yml`, implemented 2026-07-28. It
runs every gate below on pull requests and on pushes to `main`. Tool versions are
pinned in the workflow's `env` block and each downloaded binary is verified against
its publisher's checksums file before use:

| Purpose | Tool | Version |
|---|---|---|
| Repository secret scan | gitleaks-action | v2 |
| Dependency and image vulnerabilities | Trivy | 0.72.0 |
| SBOM per application image | Syft | 1.49.0 |
| OpenAPI breaking-change detection | oasdiff | 1.26.1 |

These choices are implemented, not yet approved: `TODO(governance)` markers in the
workflow record what the security owner still has to confirm or replace. The
artifact registry, protected-branch rules, required status-check names, and evidence
retention remain open decisions.

Reviewed vulnerability exceptions live in `.trivyignore.yaml`. Every entry carries a
reason, an owner and an expiry, and the scans run with `--show-suppressed` so a
suppressed finding is printed with its justification rather than disappearing.

Image scans gate on findings that have a published fix. Base-image advisories the
distribution has marked deferred or will-not-fix cannot be cleared by rebuilding, so
they are recorded in the evidence artifact and counted in the log instead of failing
the build. Dependency scanning stays strict, because the project chooses those
versions.

## Toolchains

- Python 3.12.13
- uv 0.8.22
- Node.js 24.18 LTS
- pnpm 11.15.1 through Corepack
- Docker Engine with Compose v2
- curl for Docker HTTP smoke checks
- the Playwright Chromium binary and its operating-system dependencies

## Executable verification entry points

The scripts use frozen Python and pnpm lockfiles and never print `.env` or container
logs:

- Windows native checks: `powershell -File infra/scripts/verify-native.ps1`
- POSIX native checks: `sh infra/scripts/verify-native.sh`
- Windows Docker acceptance: `powershell -File infra/scripts/verify-docker.ps1`
- POSIX Docker acceptance: `sh infra/scripts/verify-docker.sh`
- Full Windows sequence: `powershell -File infra/scripts/verify.ps1`
- Full POSIX sequence: `sh infra/scripts/verify.sh`

The native verifier first rejects any Node.js, pnpm, uv, or project-Python version
that differs from the exact versions above. It then synchronizes the backend with
`uv sync --frozen`, installs the frontend with `pnpm install --frozen-lockfile`,
checks the committed OpenAPI outputs, and runs repository safety, the committed
high-confidence secret scanner, backend, frontend, build, and accessibility gates.
The local scanner does not replace a maintained provider/third-party
secret-scanning gate.

The Docker verifier requires a private `.env` with URL-safe, non-placeholder local
credentials and a `RELEASE_COMMIT` equal to the checked-out Git SHA. It uses an
isolated Compose project, loopback port, and per-project `.local/m1-verify` data
root; it refuses
to take over pre-existing verification containers. It validates and builds the
Compose model, verifies one-shot jobs, health checks, restricted probes, non-root
users, the reviewed `storage-init` capability exception, port isolation, release
metadata, and image IDs/digests. It writes independent non-financial PostgreSQL and
storage sentinels, recreates containers without deleting data, verifies both
sentinels, removes them, and always runs `compose down` without `--volumes`. A pass
means the automated Docker gates passed; maintained scans, SBOMs, CI evidence, and
owner acceptance remain separate requirements.

Install the frozen frontend graph and Playwright before the native verifier on a fresh
runner (the verifier repeats the frozen install as a lockfile-integrity gate):

```text
pnpm install --frozen-lockfile
pnpm --filter @gold/trader-pwa exec playwright install --with-deps chromium
```

## Required pull-request gates

1. Verify lockfiles and reject unreviewed dependency drift.
2. Run the native verification entry point for the runner operating system.
3. Compare OpenAPI against the protected-branch merge base with a pinned,
   maintained breaking-change detector; require a contract-version bump or an
   approved waiver for any breaking change.
4. Run a repository secret scan even when the optional local scanner is absent.
5. Run the Docker acceptance entry point with CI-only credentials.
6. Scan dependencies and built images for known vulnerabilities.
7. Generate and retain SBOMs for every application image.
8. Record test reports, SBOMs, image digests, source commit, and toolchain versions.

The CI adapter must provide `.env` through masked secrets or an ephemeral generated
file, never from a committed artifact. It must delete that file after the job and
must not enable shell tracing around secret material. CI credentials must not reuse
staging or production values.

Production promotion must reuse tested image digests. It must not rebuild from a moving
branch, replace a digest with a tag, or inject a frontend secret at deployment time.
