# Runbook — deploying a release

**When**: a tested commit on `main` is to become what the centre runs.

**Who**: whoever holds the server. Under OPS-001 that is also whoever holds `.env`.

**Time**: ten minutes, most of it the image build.

---

## Before you start

**Take a backup.** Not because a deployment usually loses data, but because a migration that goes
wrong is the one case where the previous state is unrecoverable without one.

```
bash infra/scripts/backup.sh \
    --database-url "postgresql://postgres:PASSWORD@127.0.0.1:5432/gold_platform" \
    --storage /srv/gold/storage \
    --out /srv/gold/backups \
    --passphrase-file /root/.gold-backup-passphrase
```

Copy it off the server before continuing. **A backup on the machine it protects is not one** — the
script says so when it finishes, and the sentence is there because this is the step people skip.

---

## 1. Check what you are about to deploy

```
git -C /srv/gold/app fetch origin
git -C /srv/gold/app log --oneline HEAD..origin/main
```

If that list is empty there is nothing to deploy. If it is long, read it: a deployment is the moment
somebody should know what changed.

---

## 2. Take the code and build

```
git -C /srv/gold/app checkout main
git -C /srv/gold/app pull --ff-only origin main

cd /srv/gold/app
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml build
```

`--ff-only` refuses to merge. A server is not where a merge is resolved.

---

## 3. Migrate, then start

```
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    run --rm migrate

docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml up -d
```

The `migrate` service runs alembic and exits. **It runs before the application starts**, not
alongside it: two backends against a half-migrated schema is how a deployment corrupts rather than
fails.

---

## 4. Confirm it is actually serving

```
curl -sf https://admin.YOURDOMAIN/api/v1/health/ready
curl -sf https://trader.YOURDOMAIN/api/v1/health/ready
```

Then check the release the running system reports matches the commit you deployed:

```
curl -s https://admin.YOURDOMAIN/api/v1/health/dependencies \
    -H "X-Operations-Token: $OPERATIONS_HEALTH_TOKEN"
```

**Both hosts, not one.** They are separate server blocks with separate access rules, and
`infra/nginx/deployment/admin-access.conf` can make the admin one unreachable while the trader one
is fine — which is the intended behaviour once OPS-004 is answered, and a surprise if you only
checked one.

---

## 5. Look at something a person uses

Open a payment request and confirm it renders. `health/ready` says the process is up; it says
nothing about whether the migration left the data usable.

---

## If any of this fails

Go to `rollback.md`. **Decide within ten minutes** — a deployment that is half-working while
somebody investigates is worse than one that has been rolled back, because the centre is taking
payment instructions the whole time.

---

## How this runbook is tested

**It is not, and that is stated rather than implied.** Every command here needs a server with a
certificate and a domain, which is M13's to provide.

What `tests/backend/test_runbooks.py` does check is narrower and still worth having: every script
this file names exists, every flag it passes is one that script accepts, and every path it cites is
real. A runbook that tells an operator to run a flag that was renamed is worse than no runbook,
because it is followed under pressure.
