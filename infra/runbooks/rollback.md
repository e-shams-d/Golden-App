# Runbook — rollback and forward-fix

**When**: a deployment is serving errors, or serving wrong answers.

**The decision this runbook exists to make**: roll back, or fix forward. Getting it wrong in either
direction costs more than the original fault.

---

## Decide first, in one question

**Did the deployment run a migration?**

```
git -C /srv/gold/app diff --name-only HEAD@{1} HEAD -- services/backend/alembic/versions/
```

| answer | do this |
|---|---|
| no new migration | **roll back.** Section 1. Minutes, and reversible. |
| a new migration ran | **fix forward.** Section 2. |

**Why a migration changes the answer.** Alembic downgrades exist and are written, but this
repository's own migrations say what they cost: `20260801_0012`'s downgrade drops four tables and
its docstring records that this is "honest only while they are empty". A bank profile version is the
configuration a batch was built against. **Rolling back a schema that has taken writes discards
those writes**, and no amount of care at 3am makes that the smaller loss.

---

## 1. Rollback — no migration ran

```
cd /srv/gold/app
git log --oneline -3                      # note the commit you are leaving
git checkout <previous-commit>

docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml build
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml up -d
```

Then `deployment.md` section 4: check **both** hosts and open one real page.

**Write down the commit you rolled back from.** The next person to deploy needs to know that `main`
contains something that failed, or they will deploy it again.

---

## 2. Forward-fix — a migration ran

The database has moved. Going back means going back through a downgrade, and §1 says why that is the
expensive direction.

1. **Decide whether the system is safe to leave running.** If it is accepting payment instructions
   and answering them wrongly, stop the backend first:
   ```
   docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
       stop backend worker scheduler
   ```
   nginx stays up so people see a page rather than a refused connection.

2. **Fix on a branch, with the gates.** Not on the server. `bash infra/scripts/verify-native.sh`
   must pass before the fix is deployed, exactly as it must for any other change — a hotfix that
   skipped the gates is how one fault becomes two.

3. Deploy the fix through `deployment.md`.

**If the migration itself is the fault** — it ran and left the data wrong — this is a restore, not a
rollback. Go to `restore.md` and use the backup `deployment.md` told you to take.

---

## What not to do

**Do not edit files on the server.** A server whose code is not a commit cannot be reasoned about,
redeployed, or rolled back, and the next deployment silently discards the fix.

**Do not skip the backup because "this is just a rollback".** Section 2 may turn into a restore
halfway through, and the backup is taken before the deployment for exactly that reason.

**Do not roll back one service.** The applications and the backend share a contract; an admin-web
from yesterday against a backend from today is a combination nothing has ever tested.

---

## How this runbook is tested

`tests/backend/test_runbooks.py` checks that the commands, flags and paths named here exist.

**The decision in section 1 is not testable** and is the part that matters. It is written as one
question with a command that answers it, rather than as advice, because the person reading this is
under time pressure and should not be weighing trade-offs from scratch.
