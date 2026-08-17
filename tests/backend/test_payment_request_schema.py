"""The request and revision tables, compared against document 04 itself.

M5 slice 3. `DB-REQ-001` and `DB-REV-001` are both "matches doc 04 column for
column", and the obvious way to prove that is to transcribe the document's table into
a Python dict and compare. Slice 1 did exactly that for `beneficiaries` — and
transcribed one type wrong, asserting `VARCHAR(26)` where document 04 says
`CHAR(26)`, because the expectation was written from the model rather than from the
document. The test passed, the deviation shipped, and nothing else in the suite
compares a column type to the specification: `test_schema_matches_the_specification.py`
is scoped to indexes and says so.

So this parses document 04's markdown tables and compares. A transcription can be
wrong in the same direction as the code; a parse cannot.

It found two things on the first run, which is the argument for having written it.

**Two deviations are recorded rather than fixed**, and both are the same one:
document 04 declares `CHAR(n)` and this repository stores `VARCHAR(n)`. That is a
convention here, not an improvisation — all three IBAN columns are `VARCHAR(26)` and
nine of the ten digest columns are `VARCHAR(64)`. PostgreSQL advises against
`char(n)`, and for a value whose length a CHECK already fixes the two cannot behave
differently. `CHAR_AS_VARCHAR_DEVIATION` is the record, and two tests at the bottom
of this file assert the consistency it rests on, because "we deviate consistently" is
a justification only while it stays true.

**And it found a bug in itself**, which is the more useful half. The first version
skipped any `Required` cell that was not exactly `yes` or `no` — so it silently
dropped `current_revision_id`, whose cell reads `no initially`, and then reported that
column as *extra in the model*. A careless reading of that failure would have deleted
a column document 04 requires. An unrecognised cell now raises.

Covers: DB-REQ-001, DB-REV-001.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
from app.db.base import Base
from sqlalchemy.dialects import postgresql

SPECIFICATION = (
    Path(__file__).resolve().parents[2]
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)

POSTGRES = postgresql.dialect()

# Document 04's spellings mapped onto what PostgreSQL renders. Written out because the
# document uses SQL-standard names and PostgreSQL renders its own: `TIMESTAMPTZ` is
# `TIMESTAMP WITH TIME ZONE`, `JSONB` is `JSONB`, and `UUID` agrees.
SPECIFICATION_TYPES: dict[str, str] = {
    "UUID": "UUID",
    "TEXT": "TEXT",
    "JSONB": "JSONB",
    "BIGINT": "BIGINT",
    "INTEGER": "INTEGER",
    "TIMESTAMPTZ": "TIMESTAMP WITH TIME ZONE",
}

# Recorded, asserted deviations. Keyed by `(table, column)` so each names exactly what
# it covers and cannot spread by accident.
#
# Both are the same deviation: document 04 declares `CHAR(n)` and this repository
# stores `VARCHAR(n)`. PostgreSQL's own documentation advises against `char(n)` — it
# blank-pads to the declared width and ignores trailing spaces when comparing, which
# is a subtle-bug generator — and for a value whose length a CHECK already fixes, the
# two cannot behave differently.
#
# It is a convention, not an improvisation: nine of the ten digest columns M2 and M4
# shipped are `VARCHAR(64)`, and all three IBAN columns are `VARCHAR(26)`. The two
# tests at the bottom of this file assert that consistency, because "we deviate
# consistently" is a justification only while it stays true.
CHAR_AS_VARCHAR_DEVIATION: dict[tuple[str, str], str] = {
    ("payment_request_revisions", "beneficiary_iban_snapshot"): (
        "document 04 says CHAR(26); all three IBAN columns are VARCHAR(26). M2 set the "
        "convention on bank_accounts and M5 slice 1 followed it."
    ),
    ("payment_request_revisions", "content_hash"): (
        "document 04 says CHAR(64); nine of the ten digest columns already shipped are "
        "VARCHAR(64). `idempotency_records.request_hash` is the single CHAR(64) in the "
        "tree and is the odd one out, not the pattern."
    ),
}


def specification_columns(heading: str) -> dict[str, tuple[str, bool]]:
    """Parse one `## 11.x `table`` section's column table out of document 04.

    Returns `{column: (type, nullable)}`. The document's `Required` column is `yes`
    or `no`, and `no` means nullable.
    """

    text = SPECIFICATION.read_text(encoding="utf-8")
    start = text.index(heading)
    # Up to the fenced SQL block that follows every table, or the next heading.
    rest = text[start + len(heading) :]
    end = min(
        (position for position in (rest.find("\n```"), rest.find("\n## ")) if position != -1),
        default=len(rest),
    )
    section = rest[:end]

    columns: dict[str, tuple[str, bool]] = {}
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        name = cells[0].strip("`")
        declared = cells[1].strip("`").upper()
        required = cells[2].lower()

        # `no initially` is document 04's wording for `payment_requests.current_revision_id`:
        # nullable, because the first revision does not exist when the request row is
        # written. An earlier version of this parser skipped any `Required` cell that
        # was not exactly `yes` or `no`, which dropped that column silently — the
        # column-set comparison then reported it as *extra* in the model, and a
        # careless reading would have deleted a column document 04 requires. Anything
        # unrecognised now fails loudly instead of being passed over.
        if required.startswith("no"):
            nullable = True
        elif required == "yes":
            nullable = False
        else:
            raise AssertionError(
                f"{heading}: column {name!r} has Required={required!r}, which this "
                "parser does not understand. Skipping it would under-check the table."
            )

        columns[name] = (declared, nullable)

    assert columns, f"parsed no columns under {heading!r}; the document's layout changed"
    return columns


def rendered(table: str, column: str) -> tuple[str, bool]:
    mapped = Base.metadata.tables[table].columns[column]
    return mapped.type.compile(POSTGRES).upper(), mapped.nullable


def expected_render(declared: str) -> str:
    """What PostgreSQL should render for a type document 04 declares."""

    if declared in SPECIFICATION_TYPES:
        return SPECIFICATION_TYPES[declared]
    match = re.fullmatch(r"(VARCHAR|CHAR)\((\d+)\)", declared)
    assert match, f"document 04 declares a type this test cannot map: {declared!r}"
    return f"{match.group(1)}({match.group(2)})"


@pytest.mark.parametrize(
    ("table", "heading"),
    [
        ("payment_requests", "## 11.1 `payment_requests`"),
        ("payment_request_revisions", "## 11.2 `payment_request_revisions`"),
    ],
)
def test_the_columns_match_document_04(table: str, heading: str) -> None:
    """DB-REQ-001 and DB-REV-001.

    Both directions. A missing column is a fact document 04 requires and the table
    cannot hold; an extra one is a fact no document defines, and the second is the
    more dangerous because nothing else would ask about it.
    """

    specified = specification_columns(heading)
    actual = set(Base.metadata.tables[table].columns.keys())

    assert actual == set(specified), (
        f"{table} does not match document 04.\n"
        f"  missing: {sorted(set(specified) - actual)}\n"
        f"  extra:   {sorted(actual - set(specified))}"
    )


@pytest.mark.parametrize(
    ("table", "heading"),
    [
        ("payment_requests", "## 11.1 `payment_requests`"),
        ("payment_request_revisions", "## 11.2 `payment_request_revisions`"),
    ],
)
def test_every_column_has_the_type_and_nullability_document_04_states(
    table: str, heading: str
) -> None:
    """DB-REQ-001 and DB-REV-001, the part slice 1 got wrong.

    Nullability matters as much as type here. `DB-REV-001`'s own wording is that
    "every snapshot column is NOT NULL where doc 04 says so: a revision that could
    omit the beneficiary name is a revision that cannot answer what was submitted".
    """

    specified = specification_columns(heading)
    problems: list[str] = []

    for column, (declared, nullable) in sorted(specified.items()):
        actual_type, actual_nullable = rendered(table, column)
        wanted_type = expected_render(declared)

        if actual_type != wanted_type and (table, column) not in CHAR_AS_VARCHAR_DEVIATION:
            problems.append(f"{column}: document 04 says {wanted_type}, model has {actual_type}")
        if actual_nullable != nullable:
            wanted = "nullable" if nullable else "NOT NULL"
            problems.append(f"{column}: document 04 says {wanted}")

    assert problems == [], "\n".join(problems)


def test_every_recorded_deviation_is_still_a_deviation() -> None:
    """Guard the guard.

    An entry in `CHAR_AS_VARCHAR_DEVIATION` for a column that now matches the document
    would be a licence nobody is using, and it would absorb the next real mismatch
    on that column in silence.
    """

    stale: list[str] = []
    for (table, column), _reason in sorted(CHAR_AS_VARCHAR_DEVIATION.items()):
        heading = f"## 11.2 `{table}`" if table == "payment_request_revisions" else None
        assert heading, f"no heading known for {table}"
        declared = specification_columns(heading)[column][0]
        actual_type, _ = rendered(table, column)
        if actual_type == expected_render(declared):
            stale.append(f"{table}.{column}")

    assert stale == [], f"recorded deviations that no longer deviate: {stale}"


def test_every_iban_column_deviates_the_same_way() -> None:
    """The consistency the deviation is justified by.

    The recorded reason is "all three deviate consistently". That is an argument only
    while it stays true, so it is asserted: a fourth IBAN column arriving as
    `CHAR(26)` — or one of these three changing — fails here rather than leaving the
    justification quietly false.
    """

    found: dict[str, str] = {}
    for name, table in sorted(Base.metadata.tables.items()):
        for column in table.columns:
            if "iban" not in column.name.lower():
                continue
            found[f"{name}.{column.name}"] = column.type.compile(POSTGRES).upper()

    normalized = {key: value for key, value in found.items() if "26" in value}

    assert normalized, "no 26-character IBAN column found; this test now checks nothing"
    assert set(normalized.values()) == {"VARCHAR(26)"}, (
        f"IBAN columns no longer agree on one type: {normalized}"
    )


def test_a_revision_has_no_machinery_for_changing_it() -> None:
    """DB-REV-001.

    No `record_version` and no `updated_at`. Both are apparatus for mutating a row,
    and this table's rows are written once. Their absence is asserted rather than
    left to the migration's grant, because a column arriving here would be the first
    step toward wanting the grant.
    """

    columns = set(Base.metadata.tables["payment_request_revisions"].columns.keys())
    assert "record_version" not in columns
    assert "updated_at" not in columns


def test_the_request_carries_no_amount_and_no_snapshot() -> None:
    """DB-REQ-001, and the half of DOC-CONFLICT-005 the schema decides.

    Document 02's `6.14` lists `amount_irr`, the entered-amount pair and the three
    beneficiary snapshots as fields of the request. Document 04 gives the request
    none of them. This asserts document 04's reading, which is what the M5 plan §2.2
    proposes and what the whole milestone's immutability depends on: if the request
    held the amount, a correction would edit it in place and there would be nothing
    immutable to compare against.
    """

    columns = set(Base.metadata.tables["payment_requests"].columns.keys())
    forbidden = sorted(
        column
        for column in columns
        if "amount" in column or "snapshot" in column or column == "description"
    )

    assert forbidden == [], (
        f"payment_requests carries content columns: {forbidden}. Document 04 makes it "
        "a stable aggregate and puts content on the revision; document 02's 6.14 "
        "disagrees, and DOC-CONFLICT-005 is open on exactly this."
    )


def test_the_current_revision_pointer_is_composite() -> None:
    """DB-REV-002, the structural half.

    The behavioural half — that the database really refuses another request's
    revision — needs a database and is in
    `tests/integration/test_request_revision_integrity.py`. This asserts the shape,
    so a single-column key cannot be introduced and then tested only through a code
    path that happens to pass the right value.
    """

    table = Base.metadata.tables["payment_requests"]
    composite = [
        constraint
        for constraint in table.foreign_key_constraints
        if "current_revision_id" in {element.parent.name for element in constraint.elements}
    ]

    assert len(composite) == 1, f"expected one key on current_revision_id, found {composite}"
    constraint = composite[0]

    assert [element.parent.name for element in constraint.elements] == [
        "current_revision_id",
        "id",
    ]
    assert [element.column.name for element in constraint.elements] == [
        "id",
        "payment_request_id",
    ]
    assert constraint.deferrable is True, (
        "the pointer must be deferrable: the request and its first revision reference "
        "each other and are inserted in one transaction, so an immediate check makes "
        "the ordinary path impossible"
    )


def test_the_revision_pair_is_unique_so_the_composite_key_can_exist() -> None:
    """DB-REV-002.

    `UNIQUE(id, payment_request_id)` is what the composite foreign key references. It
    looks redundant beside the primary key on `id` alone and is not: PostgreSQL
    requires a unique constraint on the exact referenced column pair.
    """

    table = Base.metadata.tables["payment_request_revisions"]
    pairs = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("id", "payment_request_id") in pairs, f"found {sorted(pairs)}"


def test_identical_content_is_refused_within_one_request(table_of_revisions: Any) -> None:
    """The constraint that reversed an obligation.

    `04_Database_Schema.md:901` is `UNIQUE(payment_request_id, content_hash)`. The M5
    plan's slice-5 revision obligation originally claimed identical content must be
    *permitted*;
    slice 3 read the constraints under the table the plan had cited only by line
    range, and corrected the plan. Slice 5 owns the behaviour; this asserts the
    constraint exists so the correction cannot be quietly undone.
    """

    pairs = {
        tuple(column.name for column in constraint.columns)
        for constraint in table_of_revisions.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }

    assert ("payment_request_id", "content_hash") in pairs, f"found {sorted(pairs)}"


@pytest.fixture
def table_of_revisions() -> Any:
    return Base.metadata.tables["payment_request_revisions"]
