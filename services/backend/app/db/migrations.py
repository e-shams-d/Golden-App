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
# 20260801_0006 adds processing_jobs with the claim and reclaim indexes the
# worker pattern requires.
# 20260801_0007 adds the identity and RBAC schema: two separate identity tables,
# roles, permissions and grants. Schema only; authentication behaviour is M3.
# 20260801_0008 seeds the approved roles, permissions and default grants, with
# the catalogue data inlined because docs/ is not shipped in the image.
# 20260801_0009 adds auth_sessions, auth_events and recent_auth_contexts, and
# attaches the audit foreign key slice 1 deferred until the table existed.
# 20260801_0010 adds system_settings, feature_flags and the inert retention and
# legal-hold structures, and seeds exactly the five Phase 1A flags. Nothing in it
# deletes anything: ADR-005 is open, so structure exists and no executor does.
# 20260801_0011 adds file_objects, file_links and file_derivations, with the two
# conditional constraints that make "available" mean hashed and scanned clean, and
# the first grants in this schema that withhold DELETE.
# 20260801_0012 adds the bank profile, version, account and mapping foundation:
# a composite deferrable pointer, uniques scoped so an import and an export mapping
# can share a template version, and column-level UPDATE on the immutable snapshots.
# It seeds nothing — ADR-007 permits synthetic fixtures only.
# 20260808_0013 opens M3: it adds `traders`, hangs `trader_users.trader_id` off it
# NOT NULL, and corrects two things M2 left. The primary-contact index was keyed on
# `is_primary` because `trader_id` did not exist, which made it a system-wide
# singleton rather than one primary per business; it is rebuilt on `trader_id` under
# the name doc 04 gives it. And the identity `status` columns gain the value CHECK
# DOC-CONFLICT-037 reserved until the account lifecycle was decided.
EXPECTED_MIGRATION_HEADS = frozenset({"20260816_0014"})
