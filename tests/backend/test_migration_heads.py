"""The runtime's expected Alembic heads must match the versions directory.

`app/db/migrations.py` records the heads the readiness probe demands. A revision
added without updating that constant leaves the application permanently unready
against a correctly migrated database, and the symptom is an unhealthy container
whose own logs show nothing wrong — the readiness endpoint simply answers 503
with `database: unavailable`. This test turns that into a failing unit test at
the moment the revision is written.
"""

from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.db.migrations import EXPECTED_MIGRATION_HEADS  # noqa: E402


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_expected_heads_match_the_versions_directory() -> None:
    resolved = frozenset(_script_directory().get_heads())
    assert resolved == EXPECTED_MIGRATION_HEADS, (
        "app/db/migrations.py EXPECTED_MIGRATION_HEADS is out of step with "
        f"alembic/versions. Alembic resolves {sorted(resolved)}; the constant "
        f"says {sorted(EXPECTED_MIGRATION_HEADS)}. Update the constant in the "
        "same commit as the revision, or the readiness probe reports the "
        "database unavailable against a correctly migrated schema."
    )


def test_exactly_one_head_so_upgrade_head_is_unambiguous() -> None:
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"alembic/versions has {len(heads)} heads: {sorted(heads)}. "
        "`alembic upgrade head` fails outright with multiple heads, so the "
        "migrate container cannot start. Merge the branches into one head."
    )


def test_every_revision_is_reachable_from_the_head() -> None:
    script = _script_directory()
    head = script.get_current_head()
    assert head is not None
    reachable = {revision.revision for revision in script.iterate_revisions(head, "base")}
    all_revisions = {revision.revision for revision in script.walk_revisions()}
    orphans = all_revisions - reachable
    assert not orphans, (
        f"revisions unreachable from head {head}: {sorted(orphans)}. An orphaned "
        "revision never runs, so whatever it creates is silently absent."
    )
