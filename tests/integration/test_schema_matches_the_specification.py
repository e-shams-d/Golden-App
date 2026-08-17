"""DB-SPEC-001: every index document 04 states in SQL, checked against the database.

**This is the comparison M2 never made.** The M3 plan's own retrospective says it plainly:
"M2 gated the migration against the model and the model against the tests, and never gated
either against the specification. A constraint the specification states and the code does
not is the one shape a model-versus-migration comparison can never see, because both sides
can be wrong together." `test_schema_matches_models.py` compares the database to
`Base.metadata`; `test_constraint_names.py` compares names to what the models compile to.
Neither has ever read `04_Database_Schema.md`.

Two defects found while planning slice 1 rather than by the suite were exactly this shape.

## Why this is a ledger and not a pass/fail

Building this gate surfaced roughly forty pre-existing divergences across tables M2 shipped.
Every one of them is either fixed or **written down with a disposition** below. The gate
fails on any divergence that is not in the ledger, which is the only arrangement that
distinguishes "we know about this" from "nobody checked" — the same distinction
`RECORDED_GAPS` makes in `tests/backend/test_traceability.py`, and the reason that file
exists at all.

An entry here is a commitment, not an exemption. `test_no_disposition_is_stale` fails on a
ledger entry whose divergence no longer exists, so the ledger cannot quietly accumulate
permissions for things that were fixed.

## What this proves, and what it does not

It proves that every index doc 04 names exists, on the table it names, with the uniqueness
it states, and with a partial predicate mentioning the same identifiers and literals.

It does **not** prove the predicates are semantically equivalent. PostgreSQL renders a
stored predicate with its own casts, parenthesisation and operator spellings, so comparing
text would fail on every row for reasons that are not defects. Comparing the *token set*
catches the divergence that matters — a predicate naming a different column or a different
value, which is what "narrowed silently" means — and misses a reordering that changes
meaning while reusing the same words. Stating the limit because a gate whose reach is
assumed to be wider than it is converts an unchecked claim into an apparently-checked one.

Covers: DB-SPEC-001.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)

sys.path.insert(0, str(REPOSITORY_ROOT / "services" / "backend"))


class Divergence(str):
    """A reason, and a string so the ledger reads as a mapping of name to explanation."""


# Every index doc 04 states that the database does not carry as stated, with why.
#
# Grouped by cause rather than alphabetically, because the causes are the finding: three
# quarters of this ledger is "a later milestone owns this table", which is a different
# statement from "we disagreed with the specification" and must not be filed as the same
# thing.
_RENAMED_AGAINST_042 = (
    "Renamed against DOC-CONFLICT-042, whose approved resolution is that an index document "
    "04 names keeps that name verbatim. The object exists and does the same work under a "
    "different name — {live} — so nothing is unindexed; what is wrong is that an approved "
    "rule was not followed and nothing reported it. Renaming six indexes is a migration "
    "with its own downgrade path and its own tests, which is a slice rather than a line in "
    "this ledger. Owed by the slice that does it; the register row now says so."
)

DISPOSITIONS: dict[str, Divergence] = {
    # SIX INDEXES RENAMED AGAINST AN APPROVED RESOLUTION.
    #
    # This is slice 1B's finding, and it is not "forty divergences". DOC-CONFLICT-042 was
    # approved on 2026-08-06 with the rule "an index doc 04 names keeps that name, written
    # explicitly as `Index('idx_...')`", and its evidence column claims
    # "tests/integration/test_constraint_names.py asserts the doc-04 names exist verbatim".
    # That test compares the database to what the *models* compile to. It has never read
    # document 04. So the rule was approved, the evidence was recorded, nothing enforced it,
    # and six names drifted while a governance record said they could not.
    #
    # Each one is a real object doing the specified work under another name, so nothing is
    # unindexed and no query is slow. The cost is entirely in the register having been
    # wrong, which `test_a_conflict_register_row_names_evidence_that_exists` now prevents.
    "uq_admin_users_phone": Divergence(
        _RENAMED_AGAINST_042.format(live="uq_admin_users_phone_number")
    ),
    "idx_auth_sessions_admin_active": Divergence(
        _RENAMED_AGAINST_042.format(live="idx_auth_sessions_active_admin")
    ),
    "idx_auth_sessions_trader_active": Divergence(
        _RENAMED_AGAINST_042.format(live="idx_auth_sessions_active_trader")
    ),
    "uq_admin_user_role_active": Divergence(
        _RENAMED_AGAINST_042.format(live="uq_admin_user_roles_live_grant")
    ),
    # These two are renamed *and* their columns are: doc 04 writes `file_links(entity_type,
    # entity_id, link_type)` and `audit_logs(event_type, created_at)`, and the tables carry
    # `resource_type/resource_id/link_role` and `action/occurred_at`. So the doc-04 name
    # could not be used verbatim even if somebody wanted to — the columns it names do not
    # exist. That is a documentation defect rather than a schema one, and it is a different
    # repair from the four above.
    "idx_file_links_entity": Divergence(
        "Document 04 names columns this table does not have — `entity_type`, `entity_id` "
        "and `link_type` against the schema's `resource_type`, `resource_id` and "
        "`link_role`. `idx_file_links_active` covers the same three columns under their "
        "real names with the same `replaced_at IS NULL` predicate. The doc-04 name cannot "
        "be adopted verbatim because the columns it references do not exist, so this is a "
        "documentation correction owed to doc 04's owner, not a migration."
    ),
    "idx_audit_event_time": Divergence(
        "Same shape: document 04 writes `audit_logs(event_type, created_at DESC)` and the "
        "table carries `action` and `occurred_at`. `idx_audit_action_time` is the same "
        "index under the schema's own column names. A documentation correction, not a "
        "migration — adopting the doc-04 spelling would create an index on columns that do "
        "not exist."
    ),
    # THE ONE GENUINE ABSENCE.
    "idx_admin_users_status": Divergence(
        "Genuinely absent: no index covers `admin_users(status)` under any name. Recorded "
        "rather than added because adding it is a migration, and because the cost today is "
        "nil — the staff list is unpaged over a population of tens (see "
        "`admin_user_lifecycle.list_admin_users`, which records that decision), so a "
        "sequential scan of that table is cheaper than the index. It becomes real when a "
        "deployment has enough staff accounts to page, which is the milestone that should "
        "create it."
    ),
    # A PREDICATE DIVERGENCE THAT IS AN APPROVED DECISION.
    "uq_trader_users_one_primary": Divergence(
        "The predicate names `'deactivated'` and document 04 writes `'inactive'`. That is "
        "DOC-CONFLICT-037's approved four-value account set — active, suspended, "
        "recovery_required, deactivated — which M3 slice 1 implemented and which document "
        "04 predates. `'inactive'` is a value `ck_trader_users_status` now refuses, so the "
        "doc-04 predicate would be a condition no row could satisfy: a partial index over "
        "the empty set, which is worse than a wrong one because it looks deliberate. "
        "`DB-PRIMARY-003` is the test that couples the two halves of that decision."
    ),
    # A PREDICATE DIVERGENCE THE CODE ALREADY EXPLAINS.
    "idx_outbox_dispatch": Divergence(
        "Document 04's predicate is `status IN ('pending','retry')`; the model's own "
        "docstring (`app/db/models/outbox_event.py:9-11`) records that `retry` is not one "
        "of the five canonical values in `status_catalog.yaml` and that the doc-04 "
        "predicate is deliberately not copied. The live index covers the claimable set the "
        "dispatcher actually queries. This entry exists so the divergence is visible from "
        "the ledger as well as from the model."
    ),
}

# Tables whose indexes belong to milestones that have not run. Doc 04 specifies the whole
# Phase 1A schema; M2 created the tables it needed and M3 added identity. An index on a
# table that does not exist yet is not a divergence from the specification, it is work that
# has not started — and filing it as a divergence would bury the four that are real.
#
# Derived rather than listed: the gate skips an index whose table is absent, and
# `test_every_specified_table_that_exists_is_checked` is what stops that skip from
# swallowing a table that does exist.

_INDEX = re.compile(
    r"CREATE\s+(?P<unique>UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?P<name>[a-z_][a-z0-9_]*)\s*\n?"
    r"\s*ON\s+(?P<table>[a-z_][a-z0-9_]*)\s*(?P<rest>[^;]*);",
    re.I,
)

# Identifiers and literals inside a predicate, which is what the comparison uses. Casts,
# parentheses and operator spellings are deliberately not captured — see the module
# docstring for why comparing rendered text would fail on every row.
_TOKEN = re.compile(r"'[^']*'|[a-z_][a-z0-9_]*", re.I)

# Words PostgreSQL adds or drops when rendering a predicate, and SQL keywords that carry no
# information about *which* rows a partial index covers. Removed from both sides so the
# comparison is about the columns and values named.
_NOISE = frozenset(
    {
        "where", "and", "or", "not", "is", "null", "true", "false",
        "text", "character", "varying", "timestamp", "with", "time", "zone",
        "boolean", "uuid", "bigint", "integer", "numeric", "citext",
        # M5 slice 3. PostgreSQL stores `status IN ('a','b')` as
        # `status = ANY (ARRAY['a','b'])`, so a document that writes `IN` and a database
        # that renders `ANY`/`ARRAY` describe the same rows in different spelling — the
        # rendering difference this token-set comparison exists to tolerate, per the note
        # at the top of this file.
        #
        # `idx_payment_requests_queue` is the first partial index in the tree whose
        # predicate uses `IN`; every earlier one compares a single value, so the
        # divergence could not appear until now. The column and all six literals still
        # compare exactly, which is what catches a differently-scoped index — dropping
        # the operator spelling leaves that intact.
        "in", "any", "array",
    }
)


def specified_indexes() -> dict[str, dict[str, Any]]:
    """Every index doc 04 states, keyed by name."""

    text = SPECIFICATION.read_text(encoding="utf-8")
    found: dict[str, dict[str, Any]] = {}
    for match in _INDEX.finditer(text):
        name = match.group("name").lower()
        rest = match.group("rest")
        predicate = ""
        if (where := re.search(r"\bWHERE\b(.*)", rest, re.I | re.S)) is not None:
            predicate = where.group(1)
        found[name] = {
            "unique": bool(match.group("unique")),
            "table": match.group("table").lower(),
            "predicate": predicate,
        }
    return found


def tokens(predicate: str) -> frozenset[str]:
    return frozenset(
        token.lower() for token in _TOKEN.findall(predicate) if token.lower() not in _NOISE
    )


@pytest.fixture
def migrated(provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=provisioned_database.app_role,
        worker_role=provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return provisioned_database


@pytest.fixture
def database(migrated: RuntimeIdentities) -> Iterator[Any]:
    url = migrated.owner_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(url) as connection:
        yield connection


def live_indexes(connection: Any) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        "SELECT indexname, tablename, indexdef FROM pg_indexes WHERE schemaname = 'public'"
    ).fetchall()
    live: dict[str, dict[str, Any]] = {}
    for name, table, definition in rows:
        predicate = ""
        if (where := re.search(r"\bWHERE\b(.*)", definition, re.I | re.S)) is not None:
            predicate = where.group(1)
        live[name.lower()] = {
            "unique": "CREATE UNIQUE INDEX" in definition.upper(),
            "table": table.lower(),
            "predicate": predicate,
            "definition": definition,
        }
    return live


def existing_tables(connection: Any) -> frozenset[str]:
    return frozenset(
        row[0].lower()
        for row in connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    )


def test_the_specification_still_states_indexes_in_sql() -> None:
    """Guard the guard: a pattern that stopped matching would make every check below empty.

    The floor is high on purpose. Doc 04 states forty-three `CREATE INDEX` statements; a
    parser returning three would still produce a comparison, and that comparison would pass
    while covering almost nothing.
    """

    specified = specified_indexes()

    assert len(specified) >= 35, (
        f"only {len(specified)} indexes were parsed out of {SPECIFICATION.name}, which is "
        "far fewer than it states — the pattern no longer matches how the document writes "
        "them, and every comparison below is now about almost nothing"
    )


def test_every_specified_index_on_an_existing_table_is_present(database: Any) -> None:
    """The comparison M2 never made, restricted to tables that exist.

    An index on a table a later milestone creates is not a divergence; it is work that has
    not started. The restriction is what keeps that from burying the real findings — and
    `test_every_specified_table_that_exists_is_checked` is what stops it swallowing a table
    that does exist.
    """

    specified = specified_indexes()
    live = live_indexes(database)
    tables = existing_tables(database)

    missing = sorted(
        name
        for name, index in specified.items()
        if index["table"] in tables and name not in live and name not in DISPOSITIONS
    )

    assert missing == [], (
        "document 04 states these indexes on tables that exist, and the database does not "
        f"carry them: {missing}. Either create them or record a disposition in "
        "DISPOSITIONS saying why the specification is not being followed."
    )


def test_every_present_index_matches_what_the_specification_states(database: Any) -> None:
    """Uniqueness, table and predicate tokens — the three that carry meaning.

    Uniqueness is the one that would be silent otherwise: a `UNIQUE` index the code created
    as an ordinary one enforces nothing, and every read of it still works.
    """

    specified = specified_indexes()
    live = live_indexes(database)
    problems: list[str] = []

    for name, index in specified.items():
        actual = live.get(name)
        if actual is None or name in DISPOSITIONS:
            continue
        if actual["unique"] != index["unique"]:
            problems.append(
                f"{name}: document 04 states "
                f"{'UNIQUE' if index['unique'] else 'non-unique'} and the database has "
                f"{'UNIQUE' if actual['unique'] else 'non-unique'} — an index that should "
                "enforce uniqueness and does not enforces nothing, silently"
            )
        if actual["table"] != index["table"]:
            problems.append(
                f"{name}: document 04 puts it on {index['table']} and it is on "
                f"{actual['table']}"
            )
        expected_tokens = tokens(index["predicate"])
        actual_tokens = tokens(actual["predicate"])
        if expected_tokens and expected_tokens != actual_tokens:
            problems.append(
                f"{name}: the partial predicate names {sorted(actual_tokens)} and document "
                f"04 states {sorted(expected_tokens)}. A predicate naming a different "
                "column or value is a differently-scoped index wearing the right name."
            )

    assert problems == [], "\n".join(problems)


def test_no_disposition_is_stale(database: Any) -> None:
    """A ledger entry for a divergence that no longer exists is a licence nobody is using.

    Without this, the ledger accumulates: somebody fixes an index, leaves the entry, and the
    next real divergence under that name is absorbed by a note explaining a different
    problem that was solved months ago.
    """

    specified = specified_indexes()
    live = live_indexes(database)
    tables = existing_tables(database)

    stale = sorted(
        name
        for name in DISPOSITIONS
        if name in specified
        and specified[name]["table"] in tables
        and name in live
        and live[name]["unique"] == specified[name]["unique"]
        and live[name]["table"] == specified[name]["table"]
        and (
            not tokens(specified[name]["predicate"])
            or tokens(specified[name]["predicate"]) == tokens(live[name]["predicate"])
        )
    )

    assert stale == [], (
        f"these dispositions describe divergences that no longer exist: {stale}. Remove "
        "them, so the ledger keeps meaning 'known and accepted' rather than 'once was'."
    )


def test_every_disposition_names_a_reason() -> None:
    """A bare marker would make the ledger a list of names nobody has to justify."""

    thin = sorted(name for name, reason in DISPOSITIONS.items() if len(reason) < 40)

    assert thin == [], f"these dispositions carry no usable reason: {thin}"


def test_every_specified_table_that_exists_is_checked(database: Any) -> None:
    """The floor under the skip. Without it, an empty database passes everything.

    The comparison above ignores indexes whose table is absent. If the migrations stopped
    creating tables — or the fixture ran against the wrong database — every index would be
    skipped and every assertion would pass over nothing.
    """

    specified = specified_indexes()
    tables = existing_tables(database)
    checked = {name for name, index in specified.items() if index["table"] in tables}

    assert len(tables) >= 20, (
        f"only {len(tables)} tables exist in the migrated database, which is fewer than "
        "the migrations create — this run is not against a migrated schema"
    )
    assert len(checked) >= 8, (
        f"only {len(checked)} specified indexes are on tables that exist, so this gate is "
        "comparing almost nothing. Either the parser or the migration set has changed."
    )
