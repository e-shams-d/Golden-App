"""`confirmed_evidence_links` matches §12.6, and its transitions match §22.

`DB-EVIDENCE-001`, the half that needs no database. The other half — that the two partial unique
indexes actually *refuse* a second active primary — is
`tests/integration/test_evidence_links.py`, because an index's existence and an index's effect are
different claims and only one of them can be read from a model.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.db.models.confirmed_evidence_link import (
    DEPRECATED_REVOKED_ALIAS,
    LINK_ACTIVE,
    LINK_REPLACED,
    LINK_REVOKED,
    LINK_STATUSES,
    LINK_TYPES,
    PERMITTED_TRANSITIONS,
    ConfirmedEvidenceLink,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = REPOSITORY_ROOT / "Implementation Docs" / "02_Architecture_and_Contracts"
SCHEMA = DOCUMENTS / "04_Database_Schema.md"
WORKFLOWS = DOCUMENTS / "06_Workflows_and_State_Machines.md"

SECTION = re.compile(r"## 12\.6 `confirmed_evidence_links`\n(.*?)\n---", re.S)


@pytest.fixture(scope="module")
def section() -> str:
    match = SECTION.search(SCHEMA.read_text(encoding="utf-8"))
    assert match is not None, "§12.6 has moved or been retitled; this file reads nothing"
    body = match.group(1)
    assert body.strip(), "§12.6 parsed empty, so every comparison below is vacuous"
    return body


def test_every_documented_column_exists(section: str) -> None:
    """§12.6 is a table, so the column names are in the first cell of each row."""

    documented = {
        match.group(1)
        for match in re.finditer(r"^\| `([a-z_]+)` \|", section, re.M)
    }
    assert len(documented) >= 10, f"only {len(documented)} columns parsed; §12.6 changed shape"

    actual = set(ConfirmedEvidenceLink.__table__.columns.keys())
    missing = sorted(documented - actual)

    assert missing == [], f"§12.6 documents these and the table has none of them: {missing}"


def test_the_table_adds_no_column_the_document_does_not_document(section: str) -> None:
    """The direction that catches an invented column.

    §22.3 requires a revocation reason and §12.6 gives no column for one — the reason lives on the
    audit row instead, and this test is what would have caught the alternative.
    """

    documented = {
        match.group(1)
        for match in re.finditer(r"^\| `([a-z_]+)` \|", section, re.M)
    }
    actual = set(ConfirmedEvidenceLink.__table__.columns.keys())
    extra = sorted(actual - documented)

    assert extra == [], (
        f"these columns are not in §12.6: {extra}. Adding one is a named deviation with a "
        "conflict id, not a quiet convenience."
    )


def test_both_partial_unique_indexes_carry_the_documented_predicate(section: str) -> None:
    """§12.6 at `:1297`, both of them, predicate included.

    The predicate is the whole constraint: an unconditional unique on `payment_attempt_id` would
    permit no second link at all, not merely no second *active primary* one — and replacement,
    which §12.6 requires, would become impossible.
    """

    for name in ("uq_attempt_active_primary_evidence", "uq_segment_active_primary_attempt"):
        assert name in section, f"§12.6 no longer names {name}; this test compares against a stale"

    indexes = {index.name: index for index in ConfirmedEvidenceLink.__table__.indexes}
    for name, column in (
        ("uq_attempt_active_primary_evidence", "payment_attempt_id"),
        ("uq_segment_active_primary_attempt", "receipt_segment_id"),
    ):
        index = indexes.get(name)
        assert index is not None, f"{name} is not declared on the model"
        assert index.unique, f"{name} is not unique, so it constrains nothing"
        assert [c.name for c in index.columns] == [column], name

        predicate = str(index.dialect_options["postgresql"].get("where", ""))
        assert "link_type = 'primary'" in predicate, f"{name}: {predicate}"
        assert "status = 'active'" in predicate, f"{name}: {predicate}"


def test_supplementary_links_are_unconstrained_by_design() -> None:
    """§17 `:1115`'s third rule, which is expressed by an absence.

    A reader who finds two indexes where the document states three rules would reasonably suspect
    one was forgotten. This is the assertion that says it was not: there is no third index, and
    that is what "multiple supplementary evidence records allowed" means.
    """

    predicates = [
        str(index.dialect_options["postgresql"].get("where", ""))
        for index in ConfirmedEvidenceLink.__table__.indexes
    ]
    assert not any("supplementary" in predicate for predicate in predicates), predicates

    names = sorted(index.name or "" for index in ConfirmedEvidenceLink.__table__.indexes)
    assert len(names) == 2, (
        f"a third index appeared on this table: {names}. If it constrains supplementary links, "
        "§17 `:1115` says it must not."
    )


def test_the_statuses_are_the_catalogue_canonical_three() -> None:
    """`voided` is a deprecated alias and is not admitted.

    `status_catalog.yaml` holds `revoked` canonical with `voided` aliased and marked provisional;
    documents 06 and 08 say `revoked`, 04 and 05 say `voided`. The CHECK takes the canonical side,
    which is the precedent DOC-CONFLICT-016 set for `bank_export`.
    """

    assert LINK_STATUSES == (LINK_ACTIVE, LINK_REPLACED, LINK_REVOKED)
    assert DEPRECATED_REVOKED_ALIAS not in LINK_STATUSES

    checks = " ".join(
        str(constraint.sqltext)
        for constraint in ConfirmedEvidenceLink.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert f"'{DEPRECATED_REVOKED_ALIAS}'" not in checks, (
        "the deprecated spelling reached the CHECK, so a row could be stored under a status the "
        "status catalogue does not make canonical"
    )


def test_the_workflow_document_draws_exactly_these_arrows() -> None:
    """§22.3's two arrows, parsed from the document rather than restated.

    `active --> replaced` and `active --> revoked`, and nothing out of either terminal state.
    """

    text = WORKFLOWS.read_text(encoding="utf-8")
    start = text.index("# 22. Confirmed Evidence Link Workflow")
    section = text[start : text.index("\n---", start)]

    arrows = {
        (match.group(1), match.group(2))
        for match in re.finditer(r"^\s*(\w+) --> (\w+):", section, re.M)
    }
    assert arrows, "§22's diagram parsed no arrows; this comparison is vacuous"

    for source, target in arrows:
        assert target in PERMITTED_TRANSITIONS[source], f"{source} --> {target} is not permitted"

    assert PERMITTED_TRANSITIONS[LINK_REPLACED] == frozenset()
    assert PERMITTED_TRANSITIONS[LINK_REVOKED] == frozenset()


def test_the_link_types_are_the_documented_two(section: str) -> None:
    assert "`primary`, `supplementary`" in section, "§12.6's link_type values have changed"
    assert LINK_TYPES == ("primary", "supplementary")


def test_a_replacement_reason_cannot_stand_alone() -> None:
    """Not in §12.6, and it closes the shape M8 found in the bbox CHECK.

    A row claiming to replace something must say why, and a row that replaced nothing must not
    carry a replacement reason — decidable by the database rather than left to a service.
    """

    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in ConfirmedEvidenceLink.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    # `named_check` prefixes `ck_<table>_`, so the names are compared by suffix — and the prefix
    # is the reason both are short: it spends 28 of PostgreSQL's 63 bytes before the name starts.
    suffixes = {name.removeprefix("ck_confirmed_evidence_links_") for name in checks}
    assert "replacement_needs_a_reason" in suffixes, sorted(suffixes)
    assert "a_link_does_not_replace_itself" in suffixes, sorted(suffixes)
