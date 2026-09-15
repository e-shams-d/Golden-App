# Runbook — restoring from a backup

**When**: the database is lost or corrupt, or a file has gone missing and the audit trail says it
should be there.

**Who**: whoever holds the backup passphrase. That is an operator decision under OPS-001, and the
answer on 2026-09-13 was a protected file on the server with an encrypted copy off it.

**Time**: a few minutes for a small deployment. The reconciliation is the slow part and is not
optional.

---

## Before you start

**Stop the application.** Restoring under a running backend gives you a database that changes while
it is being written into.

```
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    stop backend worker scheduler admin-web trader-pwa
```

nginx and postgres stay up: nginx so the outage is a page rather than a refused connection, postgres
because you are about to restore into it.

---

## 1. Decide which database you are restoring into

**A drill restores into an empty database.** `restore.sh` refuses a target that already has rows
unless you pass `--force`, and that refusal is the point: rows that were already there reconcile
with any manifest, so a drill run over live data proves nothing and destroys what it was protecting.

**A real recovery is a restore over a broken database**, and then `--force` is correct. Type it
deliberately.

---

## 2. Restore

```
bash infra/scripts/restore.sh \
    --bundle /path/to/golden-backup-YYYYMMDDTHHMMSSZ.tar.gpg \
    --database-url "postgresql://postgres:PASSWORD@127.0.0.1:5432/gold_platform" \
    --storage /srv/gold/storage \
    --passphrase-file /root/.gold-backup-passphrase \
    --force
```

The script refuses a bundle that is missing any of its three parts — database dump, storage archive,
manifest — because a bundle missing one restores a lie.

---

## 3. Put ownership back — **this step is not optional and the script cannot do it**

`pg_restore --no-owner` leaves every restored object owned by the role that connected. The
application's roles then have no rights on their own tables, and the backend fails with
`permission denied for table ...` on its first request.

```
docker compose -f infra/compose/compose.local.yml exec -T postgres \
    psql -U postgres -d gold_platform -f /docker-entrypoint-initdb.d/020-runtime-roles.sql
```

**Why the restore does not do this for you**: the grants are M2's column-level decisions — the
runtime may update `status` on an immutable snapshot and nothing else — and re-deriving them from a
dump would mean a script deciding what the runtime may write. The bootstrap file is where that
belongs.

---

## 4. Reconcile — a restore that ran is not a restore that is correct

`pg_restore` exits zero having skipped objects it could not create. The manifest is what tells you
whether the data is there.

```
# The manifest the backup recorded, extracted from the bundle:
tar -xf golden-backup-*.tar manifest.json

# What the restored system now holds:
python3 - <<'PY'
import json, sys
sys.path.insert(0, "infra/scripts")
import backup_manifest
from pathlib import Path
url = "postgresql://postgres:PASSWORD@127.0.0.1:5432/gold_platform"
m = backup_manifest.build(backup_manifest.NetworkPsql(url), Path("/srv/gold/storage"))
Path("restored.json").write_text(json.dumps(m, indent=2, sort_keys=True))
PY

python3 infra/scripts/backup_manifest.py manifest.json restored.json
```

It prints `restore reconciles` or every difference it found — **all of them, not the first**, so
three lost tables are one conversation rather than three.

**What it compares**: a row count *and a digest over identifying columns* for every table, and a
digest of the **bytes on disk** for every stored file. Not `file_objects.sha256_hash` against
itself, which would have the system agreeing with itself while both sides were wrong.

---

## 5. Start the application and check one real thing

```
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    start backend worker scheduler admin-web trader-pwa
```

Then open a payment request that existed before the failure and confirm its evidence renders. The
reconciliation proves the bytes are there; this proves they are reachable through the application,
which is a different claim.

---

## How this runbook is tested

`tests/integration/test_backup_restore_drill.py` performs steps 1, 2 and 4 against a real
PostgreSQL on every run of the verifier: it seeds a world, backs it up, restores into a **second
clean** database, and reconciles. Six negative controls assert that the reconciliation fails when it
should — including a table that lost rows, a row changed without changing the count, and a stored
file with the same size and different bytes.

**Steps 3 and 5 are not covered by a test**, and that is stated rather than implied. Step 3 needs a
running compose stack; step 5 needs a person looking at a screen. Both are M13's to exercise. The
drill reads the restored database as the role that restored it precisely so it does not quietly
pass over the ownership question.
