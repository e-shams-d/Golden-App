"""Runtime migration compatibility constants."""

from __future__ import annotations

# The M1 migration is intentionally empty: it proves deterministic Alembic
# wiring and creates only Alembic's own version marker.
EXPECTED_MIGRATION_HEADS = frozenset({"20260720_0001"})
