"""The beneficiary table, and the constraint that must never be added to it.

M5 slice 1. These read `Base.metadata` rather than a live database: they are claims
about what the schema *says*, and `tests/integration/test_schema_matches_models.py`
is what proves the database agrees with it. Splitting them that way means a failure
here names the model and a failure there names the drift.

The load-bearing test is `test_no_unique_makes_a_beneficiary_iban_or_name_one_per_row`,
and it is written against `IBAN_UNIQUE_IS_PERMITTED_ONLY_ON` — the allowlist M2 wrote
in `app/db/models/bank.py` before this table existed — rather than against a list of
constraint names. A test that named the constraints would pass just as happily after
somebody added a new one under a new name, which is exactly how the prohibition would
be lost.

Covers: DB-BEN-001, DB-BEN-002, DB-BEN-003, DB-TRADER-002.
"""

from __future__ import annotations

from typing import Any

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base
from app.db.models.bank import IBAN_PATTERN, IBAN_UNIQUE_IS_PERMITTED_ONLY_ON
from app.db.models.beneficiary import BENEFICIARY_STATUSES, VERIFICATION_STATUSES
from sqlalchemy.dialects import postgresql

TABLE = "beneficiaries"

# Types are compiled against PostgreSQL rather than stringified generically. Under
# the generic dialect `DateTime(timezone=True)` and a naive `DateTime()` both render
# as `DATETIME`, so the assertion below would accept a naive timestamp column — and
# the money/time contract is that every stored instant is `TIMESTAMPTZ`.
POSTGRES = postgresql.dialect()

# `04_Database_Schema.md:495-513`, column for column and in document order. Written
# out rather than derived from the model, because deriving it from the model would
# compare the model against itself.
EXPECTED_COLUMNS: dict[str, tuple[str, bool]] = {
    "id": ("UUID", False),
    "trader_id": ("UUID", False),
    "full_name": ("VARCHAR(255)", False),
    "normalized_name": ("VARCHAR(255)", True),
    "iban": ("VARCHAR(34)", False),
    "normalized_iban": ("VARCHAR(26)", False),
    "bank_profile_id": ("UUID", True),
    "national_id": ("VARCHAR(16)", True),
    "phone_number": ("VARCHAR(32)", True),
    "status": ("VARCHAR(24)", False),
    "blocked_reason": ("TEXT", True),
    "notes_internal": ("TEXT", True),
    "verification_status": ("VARCHAR(24)", False),
    "verification_metadata": ("JSONB", False),
    "record_version": ("BIGINT", False),
    "created_at": ("TIMESTAMP WITH TIME ZONE", False),
    "updated_at": ("TIMESTAMP WITH TIME ZONE", False),
}


@pytest.fixture(scope="module")
def table() -> Any:
    assert TABLE in Base.metadata.tables, f"{TABLE} is not mapped"
    return Base.metadata.tables[TABLE]


def test_the_columns_match_document_04(table: Any) -> None:
    """DB-BEN-001.

    Column for column, in both directions. A missing column is a fact document 04
    requires and this table cannot hold; an extra one is a fact no document defines,
    and the second is the more dangerous because nothing else in the suite would ask
    about it.
    """

    actual = {
        name: (column.type.compile(POSTGRES).upper(), column.nullable)
        for name, column in table.columns.items()
    }
    expected = {name: (spec[0].upper(), spec[1]) for name, spec in EXPECTED_COLUMNS.items()}

    assert actual == expected


def test_normalized_iban_is_not_null_and_shaped(table: Any) -> None:
    """DB-BEN-001.

    Both halves matter and they fail differently. Without NOT NULL a destination
    with no IBAN can be stored and will fail at the bank export; without the regex a
    typo is stored and fails at the bank.

    The predicate must also be **null-intolerant** here, unlike `bank_accounts`. A
    tolerant one would pass every test in this file while describing a state the
    NOT NULL makes unreachable — and the next person to copy it onto a nullable
    column would inherit a constraint that quietly permits NULL.
    """

    assert table.columns["normalized_iban"].nullable is False

    predicates = _check_predicates(table)
    shape = [text for text in predicates if "normalized_iban" in text]

    assert shape == [f"normalized_iban ~ '{IBAN_PATTERN}'"], (
        f"expected exactly one null-intolerant IBAN shape CHECK, found {shape}"
    )


def test_no_unique_makes_a_beneficiary_iban_or_name_one_per_row() -> None:
    """DB-BEN-002.

    The prohibition document 04 states in terms, asserted against M2's allowlist
    rather than against a list of constraint names: a name-based test would pass
    after a new constraint arrived under a new name.

    Scanned across **every** mapped table, not just this one. A unique index on a
    later table that pairs a trader with an IBAN would re-impose the same rule from
    somewhere else, and the trader would meet it as an unexplained error while
    typing a second account for the same person.
    """

    offenders: list[str] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        for constraint in table.constraints:
            if constraint.__class__.__name__ != "UniqueConstraint":
                continue
            offenders.extend(
                _forbidden(table_name, column.name, sorted(c.name for c in constraint.columns))
                for column in constraint.columns
            )
        for index in table.indexes:
            if not index.unique:
                continue
            offenders.extend(
                _forbidden(table_name, column.name, sorted(c.name for c in index.columns))
                for column in index.columns
            )

    found = sorted(entry for entry in offenders if entry)

    assert found == [], (
        "these unique constraints make a beneficiary IBAN or name one-per-row, which "
        f"document 04 prohibits: {found}. Duplicates are legitimate — the same person "
        "may hold two accounts and two people may share a name — and the approved "
        "behaviour is to warn, never to auto-merge."
    )


def test_the_allowlist_still_describes_something(table: Any) -> None:
    """Guard the guard for DB-BEN-002.

    `IBAN_UNIQUE_IS_PERMITTED_ONLY_ON` is the whole basis of the test above. If its
    one entry stopped matching a real unique constraint, the scan would still pass —
    it would simply be scanning for a rule nothing exercises.
    """

    del table
    for table_name, column_name in IBAN_UNIQUE_IS_PERMITTED_ONLY_ON:
        assert table_name in Base.metadata.tables, f"allowlist names a missing table: {table_name}"
        permitted = Base.metadata.tables[table_name]
        uniques = {
            column.name
            for constraint in permitted.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
            for column in constraint.columns
        }
        uniques |= {
            column.name
            for index in permitted.indexes
            if index.unique
            for column in index.columns
        }
        assert column_name in uniques, (
            f"the allowlist permits {table_name}.{column_name} to be unique and it is "
            "not, so the prohibition scan is checking an exemption nobody uses"
        )


def test_a_beneficiary_belongs_to_exactly_one_trader(table: Any) -> None:
    """DB-BEN-003.

    One `trader_id`, NOT NULL, foreign-keyed to `traders`. And nothing else through
    which a second owner could be expressed: no second trader column, no sharing
    table, no `is_shared` flag.

    DOC-CONFLICT-011's interim rule is strict trader-owned isolation. The failure a
    sharing mechanism invites is one trader paying money to another trader's
    beneficiary because a screen offered it, so M5 builds no mechanism at all rather
    than a disabled one — a flag is a thing somebody turns on.
    """

    trader_id = table.columns["trader_id"]
    assert trader_id.nullable is False
    targets = sorted(key.column.table.name for key in trader_id.foreign_keys)
    assert targets == ["traders"]

    trader_columns = sorted(column.name for column in table.columns if "trader" in column.name)
    assert trader_columns == ["trader_id"], (
        f"{TABLE} has more than one trader-shaped column: {trader_columns}. A second "
        "owner is not representable and must stay that way."
    )

    sharing = sorted(
        name
        for name in Base.metadata.tables
        if "benefic" in name and "shar" in name
    )
    assert sharing == [], f"a beneficiary sharing table exists: {sharing}"


def test_the_status_check_carries_the_catalogue_values(table: Any) -> None:
    """DB-BEN-001.

    The values themselves are compared against `status_catalog.yaml` by
    `test_status_catalogue_drift.py`; what this asserts is that the CHECK exists at
    all, so the comparison there has something to compare.
    """

    predicates = _check_predicates(table)
    status = [text for text in predicates if text.startswith("status IN")]

    expected = "status IN (" + ", ".join(f"'{value}'" for value in BENEFICIARY_STATUSES) + ")"
    assert status == [expected]


def test_verification_status_carries_no_value_check(table: Any) -> None:
    """DB-BEN-001, and DOC-CONFLICT-048.

    The deliberate absence. Four values are perfectly clear in document 04's Notes
    cell, and that is precisely why this needs a test: nothing about them looks
    uncertain, so the CHECK is the natural thing to write. What is missing is not
    clarity but approval, and a migration is the one place an unapproved vocabulary
    becomes permanent.

    `test_status_catalogue_drift.py` pins the same absence from the other side. Both
    are wanted: that one asks whether the column acquired a CHECK, this one records
    why it must not, next to the column it is about.
    """

    predicates = _check_predicates(table)
    offenders = [text for text in predicates if "verification_status" in text]

    assert offenders == [], (
        f"verification_status has acquired a CHECK: {offenders}. Its four values "
        "appear only in a Notes cell of document 04 and no approved catalogue "
        "records them — see DOC-CONFLICT-048. The tuple in "
        "app/db/models/beneficiary.py is where the vocabulary lives until the owner "
        "decides whether status_catalog.yaml gains an aggregate for it."
    )

    assert table.columns["verification_status"].nullable is False
    assert VERIFICATION_STATUSES == ("not_checked", "verified", "mismatch", "failed")


def test_both_indexes_are_trader_scoped(table: Any) -> None:
    """DB-BEN-003.

    Document 04 names both indexes and keys both on `trader_id` first. The IBAN one
    is the index a duplicate warning reads, and a global one would let that lookup
    see another trader's rows — the isolation the foreign key states, undone by a
    query plan.
    """

    keyed = {index.name: [column.name for column in index.columns] for index in table.indexes}

    assert keyed == {
        "idx_beneficiaries_trader_status": ["trader_id", "status"],
        "idx_beneficiaries_normalized_iban": ["trader_id", "normalized_iban"],
    }


def test_the_trader_status_columns_are_constrained_or_recorded() -> None:
    """DB-TRADER-002.

    Two passing states, and inventing a value set is not one of them. Either the
    trader status columns carry the CHECK the owner approved, or they carry none and
    `DELIBERATELY_UNCONSTRAINED` still records why.

    As of this slice the second holds: DOC-CONFLICT-024's values are the owner's to
    decide and the answer has not arrived, so the plan's §2.4 rule applies — the
    columns stay unconstrained and the slice ships the rest.

    The test fails if the two disagree in either direction, which is the part that
    matters later: when the CHECK is approved and added, this fails until the
    reserved-list entry comes out, so the record cannot outlive the reason for it.
    """

    from test_status_catalogue_drift import DELIBERATELY_UNCONSTRAINED, enforced_status_values

    enforced = enforced_status_values()
    for column in (("traders", "operational_status"), ("traders", "approval_status")):
        constrained = column in enforced
        recorded = column in DELIBERATELY_UNCONSTRAINED

        assert constrained != recorded, (
            f"{'.'.join(column)}: constrained={constrained}, recorded_as_reserved="
            f"{recorded}. Exactly one must hold. Both means a CHECK landed while the "
            "ledger still says the question is open; neither means the column is "
            "unconstrained with nothing saying why."
        )


def _check_predicates(table: Any) -> list[str]:
    return [
        " ".join(str(constraint.sqltext).split())
        for constraint in table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    ]


def _forbidden(table_name: str, column_name: str, columns: list[str]) -> str:
    """A unique that pins a beneficiary IBAN or name, unless the allowlist permits it."""

    if (table_name, column_name) in IBAN_UNIQUE_IS_PERMITTED_ONLY_ON:
        return ""
    if "iban" not in column_name and "name" not in column_name:
        return ""
    if "benefic" not in table_name:
        return ""
    return f"{table_name}.{column_name} (unique over {columns})"
