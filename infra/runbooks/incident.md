# Runbook — responding to an incident

**When**: something is wrong and you do not yet know what.

**The first rule**: this system moves other people's money. **Stopping is cheap; a wrong payment is
not.** If you are unsure whether to stop the backend, stop it.

---

## 1. Stop the bleeding, before diagnosing

```
cd /srv/gold/app
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    stop backend worker scheduler
```

nginx and postgres stay up: nginx so people see a page rather than a refused connection, postgres so
you can look at the data.

**The worker matters as much as the backend.** It sends bank files and processes results; a worker
left running during an incident keeps acting on whatever state caused it.

---

## 2. Find out what the system thinks happened

**The audit trail is the first place to look, not the logs.** Logs say what the software did; the
audit trail says what was decided, by whom, and against which version of the record.

```
docker compose -f infra/compose/compose.local.yml exec -T postgres \
    psql -U postgres -d gold_platform -c \
    "SELECT occurred_at, action, outcome, actor_type, entity_type, entity_id
     FROM audit_logs ORDER BY sequence_number DESC LIMIT 50"
```

Then the logs, which are structured JSON:

```
docker compose -f infra/compose/compose.local.yml logs --since 1h backend worker | tail -200
```

**`request_id` ties the two together.** An audit row and a log line carrying the same `request_id`
are the same action seen from two sides.

---

## 3. The four questions worth asking early

**Did money move that should not have?**
```
SELECT id, payment_request_id, amount_irr, status, bank_tracking_number, confirmed_at
FROM payment_attempts WHERE confirmed_at > now() - interval '24 hours' ORDER BY confirmed_at DESC;
```
A confirmation is a human act with a bank tracking number behind it. A row here with no tracking
number is the shape that should not exist.

**Did a trader see something that is not theirs?** `SEC-IDOR-001` through `005` are covered by
`tests/integration/test_trader_isolation.py`, so this is unlikely — and if it happened, the audit
row carries the `actor_id` that read it.

**Is the audit chain intact?**
```
SELECT count(*) FROM audit_logs a
JOIN audit_logs b ON b.sequence_number = a.sequence_number - 1
WHERE a.previous_event_hash IS DISTINCT FROM b.event_hash;
```
Zero is the only acceptable answer. Anything else means rows were altered or removed, and the
incident is now about the database rather than the application.

**Is anything stuck rather than broken?**
```
SELECT job_type, status, count(*) FROM processing_jobs GROUP BY 1, 2 ORDER BY 3 DESC;
```

---

## 4. Decide which runbook you are actually in

| what you found | go to |
|---|---|
| the last deployment caused it | `rollback.md` |
| data is missing or wrong and the audit says it should be there | `restore.md` |
| a credential may have been exposed | `secret-rotation.md` |
| the system is fine and one record is wrong | fix it **through the application**, so it is audited |

**The last row is the one that gets ignored.** A row corrected with `UPDATE` leaves no audit entry,
no actor, and no reason — and the next person to look at that record has no way to learn it was
touched. Every correction path in this system exists so that a fix is evidence rather than a
mystery: `POST /payment-requests/{id}/publications` for a published result,
`POST /payment-attempts/{id}/mark-retry-required` for a failed transfer.

---

## 5. Before you restart

Write down, while it is fresh:

- what you saw, and the first `request_id` that showed it;
- what you changed;
- what you have **not** yet checked.

The third is the useful one. An incident that ends with "it seems fine now" and no list of unchecked
things is one that recurs with nobody remembering why it looked familiar.

```
docker compose -f infra/compose/compose.local.yml -f infra/compose/compose.prod.yml \
    start backend worker scheduler
```

---

## How this runbook is tested

`tests/backend/test_runbooks.py` checks that every table and column the queries here name exists —
which is the part that rots. A query citing `entry_hash` when the column is `event_hash` fails at
3am, in front of somebody who has no time to debug it. That exact rename was caught while writing
this slice's backup manifest.

**The judgement in section 4 is not testable**, and is the reason this file is longer than a list of
commands.
