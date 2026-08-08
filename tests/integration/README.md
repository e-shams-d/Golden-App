# Integration tests

Use real disposable PostgreSQL and Redis containers. Redis-loss tests must prove that
no authoritative business or job fact is lost.

## Running them

They read one environment variable and **skip when it is unset**, so a clean run on a
machine without a database says `skipped`, never `failed`:

```sh
export INTEGRATION_ADMIN_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:55432/postgres"
uv run --project services/backend --frozen \
    pytest -c services/backend/pyproject.toml tests/integration
```

The identity in that URL must be allowed to `CREATE DATABASE` — each test gets a
disposable one.

The port above is the long-lived local container, started once and left running:

```sh
docker run -d --name m2-itest-pg -p 55432:5432 \
    -e POSTGRES_PASSWORD=postgres postgres:16.14-alpine3.24
```

`docker start m2-itest-pg` brings it back after a reboot. Port 55432 rather than 5432
so it cannot collide with a PostgreSQL already installed on the host.

**The version is not incidental.** DOC-CONFLICT-022 requires PostgreSQL 16 in local,
CI, staging and production, and CI uses `postgres:16.14-alpine3.24`. Nothing in the
fixtures checks the server's major version, so pointing this variable at a 15 or a 17
produces a green run that does not mean what it appears to. Point it at 16.

Full suite: about 16 minutes, because most tests provision a database and migrate it.

## Skipping is not passing

`pytest tests/integration` on a machine with no database reports `472 skipped` and
exits `0`. That is a deliberate choice — a contributor without Docker still gets a clean
`tests/backend` run — and it is a trap worth naming, because a skipped suite and a
passing one look alike in a summary line. Anything asserted about database behaviour is
unproven until this has actually run.
