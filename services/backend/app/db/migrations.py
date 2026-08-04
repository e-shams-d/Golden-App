"""Runtime migration compatibility constants.

The readiness probe compares the database's recorded Alembic heads against this
set and reports the service unready when they differ, which is what stops a
process from serving against a schema it was not built for.

That makes this constant part of every migration, not an afterthought: adding a
revision without updating it here leaves the application permanently unready
against a correctly migrated database, and the symptom — an unhealthy container
with no error in its own logs — points nowhere near the cause. A test asserts
this set matches the heads Alembic actually resolves from the versions directory.
"""

from __future__ import annotations

# The M1 baseline is intentionally empty: it proves deterministic Alembic wiring
# and creates only Alembic's own version marker. 20260801_0002 adds the pgcrypto
# and citext extensions required by 04_Database_Schema.md section 3.1.
# 20260801_0003 adds center_profile, and 20260801_0004 the integrity spine:
# audit_logs, outbox_events and idempotency_records. 20260801_0005 grants
# mutation per table now that the provisioning default is fail-closed, and
# repairs volumes whose tables were created under the old four-verb default.
EXPECTED_MIGRATION_HEADS = frozenset({"20260801_0005"})
