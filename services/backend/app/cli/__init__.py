"""Operator commands: things a person runs on the host, not through the API.

There is exactly one so far, and it exists because of a gap nothing else can close.
Every other capability in this system is reached through an authenticated request,
which presupposes an account — so the account that comes first cannot be created that
way. `18_Production_Setup_and_Runbook.md:1094-1105` requires a management command for
it, and this package is where such commands live.

**Under `app/`, deliberately, and not under `services/backend/scripts/`.** The backend
image copies `.venv`, `app/`, `alembic/`, `alembic.ini` and `pyproject.toml` and
nothing else (`infra/docker/backend.Dockerfile:29-32`), so a command written in
`scripts/` would pass its tests, be reviewed, merge, and then not exist in any
deployment. `scripts/` holds build-time tools — the OpenAPI exporter, the evidence
emitter — which run from a checkout; this holds run-time tools, which run from an
image.
"""
