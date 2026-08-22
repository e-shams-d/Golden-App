"""`batch_approvals` matches document 04 §11.7, parsed rather than transcribed.

M7 slice 1. `DB-APPROVAL-001` says "column for column, compared by **parsing** the document",
and the reason is M5 slice 1: it transcribed one type wrong and its test passed, because a
transcription can be wrong in the same direction as the code it checks.

`tests/backend/test_batch_schema.py` is the pattern and its reader is reused rather than
reimplemented — a second parser is a second thing to be wrong about what document 04 says.
Separate file rather than a fifth entry in that one, because that file is M6's four tables and
this is M7's table; folding them together would make each milestone's schema claim harder to
find than the milestone.

**Nullability is checked, and it carries more here than anywhere else in the family.**
`approved_content_hash` being nullable is what lets a rejection exist at all — §11.7 marks it
"conditional", and the CHECK pairs it with the decision. If it were NOT NULL a rejection would
have to invent a hash, and the composite foreign key that ties an approval to its version's
content would then be enforced on rows that approved nothing.

Covers: DB-APPROVAL-001.
"""

from __future__ import annotations

import re

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base
from test_payment_request_schema import (
    expected_render,
    rendered,
    specification_columns,
)

TABLE = "batch_approvals"
HEADING = "## 11.7 `batch_approvals`"

# The same recorded deviation the rest of the tree ships: document 04 declares `CHAR(n)` and this
# repository stores `VARCHAR(n)`. PostgreSQL's own documentation advises against `char(n)` — it
# blank-pads to the declared width and ignores trailing spaces when comparing — and for a value
# whose length a CHECK already fixes, the two cannot behave differently.
#
# `approved_content_hash` is compared against `payment_batch_versions.content_hash` by a foreign
# key, and that comparison is the reason this deviation must not be partial: a `CHAR(64)` here
# against a `VARCHAR(64)` there would compare a blank-padded value with an unpadded one.
CHAR_AS_VARCHAR: dict[str, str] = {
    "approved_content_hash": "CHAR(64) → VARCHAR(64), the convention, and the FK's other side",
}

# Columns this repository holds that §11.7 does not list, each with the approved authority that
# requires it. Keyed by column so an entry covers exactly one and cannot spread.
#
# Both exist for one reason: `FINANCIAL_INTEGRITY_BASELINE.md` §5 requires the separation rule to
# be enforced by "a database-enforceable guard", a CHECK cannot reach another table, and so the
# two actors it compares have to be on this row. Each is tied to the version's own value by a
# composite foreign key, so neither is a number a caller supplied — see
# `20260822_0020_batch_approvals.py` for the full argument and for why not a trigger.
APPROVED_ADDITIONS: dict[str, str] = {
    "version_finalized_by_admin_user_id": (
        "DOC-CONFLICT-055 / G-2. §5 requires `finalizer != approver` enforced by the database. "
        "`payment_batch_versions.finalized_by_admin_user_id` is itself an addition M6 made on the "
        "same authority; this is its copy on the row the CHECK evaluates, held to the version's "
        "value by `fk_batch_approvals_version_finalizer`."
    ),
    "version_created_by_admin_user_id": (
        "G-2, the stricter reading of `12_Security_RBAC_Audit.md:1111` — 'actor is not the "
        "version finalizer/preparer'. `payment_batch_version.create` and `.finalize` are "
        "separately permissioned, both defaulting to `accountant`, so the preparer and the "
        "finalizer can differ and the preparer chose every row in the file. Held to the "
        "version's value by `fk_batch_approvals_version_preparer`."
    ),
}


def test_the_columns_match_document_04() -> None:
    """Both directions. A missing column is a fact §11.7 requires and the table cannot hold.

    An extra one is the more dangerous direction, because nothing else in the system would ever
    ask about it — so extras are permitted only where `APPROVED_ADDITIONS` names the authority.
    """

    specified = specification_columns(HEADING)
    assert specified, (
        f"{HEADING} parsed to no columns; the reader has stopped seeing the section and every "
        "assertion in this file would be vacuous"
    )

    actual = set(Base.metadata.tables[TABLE].columns.keys())

    assert not (set(specified) - actual), (
        f"{TABLE} is missing columns document 04 requires: {sorted(set(specified) - actual)}"
    )
    unexplained = actual - set(specified) - set(APPROVED_ADDITIONS)
    assert not unexplained, (
        f"{TABLE} has columns no document defines and no approved baseline authorises: "
        f"{sorted(unexplained)}. Add an APPROVED_ADDITIONS entry naming the authority, or "
        "remove the column."
    )


def test_every_approved_addition_is_still_an_addition() -> None:
    """An exemption for a column document 04 now lists is a licence nobody is using.

    G-2 asks the owner whether the preparer disqualifies an approver, and DOC-CONFLICT-055 asks
    document 04 for the finalizer column. On the day either is settled and §11.7 gains the
    column, this fails and asks for the entry to go — otherwise the exemption sits here and
    absorbs the next genuinely undocumented column without anybody noticing.
    """

    specified = specification_columns(HEADING)
    stale = [
        f"{TABLE}.{column} is now in document 04; drop its entry ({reason[:60]}…)"
        for column, reason in sorted(APPROVED_ADDITIONS.items())
        if column in specified
    ]

    assert stale == [], "\n".join(stale)


def test_every_column_has_the_type_and_nullability_document_04_states() -> None:
    """Type and nullability together, because either alone is half the claim."""

    specified = specification_columns(HEADING)

    problems: list[str] = []
    for column, (declared, nullable) in sorted(specified.items()):
        actual_type, actual_nullable = rendered(TABLE, column)
        deviation = CHAR_AS_VARCHAR.get(column)

        if deviation is not None:
            match = re.fullmatch(r"CHAR\((\d+)\)", declared)
            assert match, (
                f"{TABLE}.{column} has a recorded CHAR→VARCHAR deviation but document 04 now "
                f"declares {declared!r}. Re-read the deviation before keeping it."
            )
            wanted = f"VARCHAR({match.group(1)})"
        else:
            wanted = expected_render(declared)

        if actual_type != wanted:
            problems.append(
                f"{TABLE}.{column}: document 04 says {declared} (expects {wanted}), "
                f"the model renders {actual_type}"
            )
        if actual_nullable != nullable:
            problems.append(
                f"{TABLE}.{column}: document 04 says "
                f"{'nullable' if nullable else 'NOT NULL'}, the model is "
                f"{'nullable' if actual_nullable else 'NOT NULL'}"
            )

    assert problems == [], "\n".join(problems)


def test_the_table_has_no_mutable_bookkeeping_columns() -> None:
    """Append-only in the model, not only in the grant.

    §11.7 ends "Approved/rejected rows are never updated". The runtime enforcement is an absence
    — `020-runtime-roles.sql` grants new tables SELECT and INSERT only — and this is the other
    half: a row that cannot change has nothing to version and nothing to re-stamp, so
    `updated_at` and `record_version` appearing here would mean somebody intended to mutate it.

    Cheap to assert and it names the intention. The grant is asserted separately, against a live
    database, in `tests/integration/test_approval_table_privileges.py`.
    """

    columns = set(Base.metadata.tables[TABLE].columns.keys())
    forbidden = columns & {"updated_at", "record_version"}

    assert forbidden == set(), (
        f"{TABLE} carries {sorted(forbidden)}, which only a mutable table needs. §11.7 says "
        "approved/rejected rows are never updated."
    )
