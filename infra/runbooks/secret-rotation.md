# Runbook — rotating production secrets

**OPS-001's answer, written where it is used.** The owner decided on 2026-09-13: production secrets
live in a protected file on the server, with an encrypted copy off it. No external key service —
nothing suitable is reachable from this deployment, and a rotation procedure that depends on one
would be a procedure nobody can run.

**When**: on a schedule the centre sets, and immediately if a credential may have been seen by
somebody who should not have it.

---

## Where they are

`/srv/gold/app/.env`, readable by root only:

```
chmod 600 /srv/gold/app/.env
chown root:root /srv/gold/app/.env
```

**Nothing in the repository holds a secret**, and `infra/scripts/scan_secrets.py` runs in the
verifier to keep that true. `.env.example` lists every name with no value.

---

## What is in it, and what rotating each one costs

The cost is the point: these are not interchangeable, and the cheap ones should be rotated often
rather than waiting for a day when all of them are done together.

| secret | rotating it costs |
|---|---|
| `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `WORKER_DB_PASSWORD`, `MIGRATION_DB_PASSWORD`, `READONLY_DB_PASSWORD`, `BACKUP_DB_PASSWORD` | an `ALTER ROLE` and a restart — see below |
| `REDIS_PASSWORD` | a restart. Queued jobs survive; Redis holds no durable state this system depends on |
| `AUTH_CSRF_KEY_SECRET` | **every signed-in person is signed out.** The token is derived from this and the session; changing it invalidates every one in flight |
| `AUTH_RATE_LIMIT_KEY_SECRET` | rate-limit counters reset. Harmless, and briefly forgiving to an attacker mid-attempt |
| `OPERATIONS_HEALTH_TOKEN` | any monitoring calling the health endpoints must be updated in the same change |
| `SESSION_SECRET_BYTES` | a length, not a secret. Changing it does not rotate anything |

---

## Rotating a database password

**One role at a time.** Rotating all six together means a failure you cannot attribute.

```
# 1. Change it in the database.
docker compose -f infra/compose/compose.local.yml exec -T postgres \
    psql -U postgres -c "ALTER ROLE gold_app WITH PASSWORD 'NEW_PASSWORD'"

# 2. Change it in .env — APP_DB_PASSWORD in this example.
vi /srv/gold/app/.env

# 3. Restart the services that use it. The backend and worker connect as gold_app;
#    postgres itself does not need restarting.
cd /srv/gold/app
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    up -d --force-recreate backend worker scheduler

# 4. Confirm, rather than assume.
curl -sf https://admin.YOURDOMAIN/api/v1/health/ready
```

**Steps 1 and 2 in that order.** Changing `.env` first leaves the running services holding a
password the database no longer accepts, and they fail on their next connection rather than at a
moment you chose.

**If step 4 fails**, the old password is still in the database only if step 1 has not run. Once it
has, forward is the only direction: fix `.env` and recreate again.

---

## Rotating the backup passphrase

```
# Old backups stay readable with the OLD passphrase. Keep it.
mv /root/.gold-backup-passphrase /root/.gold-backup-passphrase.until-YYYY-MM-DD
openssl rand -base64 48 > /root/.gold-backup-passphrase
chmod 600 /root/.gold-backup-passphrase
```

**Do not delete the old passphrase file.** Every existing encrypted bundle is decryptable only with
the passphrase it was written under. Deleting it destroys every backup taken before today, which is
the opposite of what a rotation is for.

Then take one backup and **restore it into a scratch database** before trusting the new passphrase —
`restore.md`, with `--passphrase-file` pointing at the new file. A passphrase nobody has decrypted
with is a passphrase that might have a typo in it.

---

## After any rotation

- Update the off-server encrypted copy of `.env`.
- Record the date and which secret, somewhere that is not the server. The question "when was this
  last rotated" has no answer otherwise, and it is the first question an auditor asks.
- **Do not record the value.**

---

## How this runbook is tested

`tests/backend/test_runbooks.py` asserts that every environment variable named here exists in
`.env.example`, so a renamed setting cannot leave this file pointing at a name nothing reads.

**The procedures are not executed by a test.** They need a running stack, which is M13's. The table
of costs is the part most worth reading before a test could ever help: it is the difference between
rotating the CSRF key at 9am and rotating it at 4pm on a day the centre is paying people.
