"""`matching_candidates` matches `04_Database_Schema.md` §12.5, and its transitions match §21.

`DB-CANDIDATE-001`. No database, so none of this can become a skip — the reason M5's
Definition-of-Done gate lives in `tests/backend` and every schema claim since has followed it.

**Read from the model, compared against the document's own text.** The alternative — restating
§12.5's field list here — would be a second copy of the specification that drifts silently, which
is what `test_schema_matches_the_specification.py` exists to prevent one layer down.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.db.models.matching_candidate import (
    CANDIDATE_ACCEPTED,
    CANDIDATE_EXPIRED,
    CANDIDATE_PROPOSED,
    CANDIDATE_REJECTED,
    CANDIDATE_STATUSES,
    CANDIDATE_SUPERSEDED,
    PERMITTED_TRANSITIONS,
    MatchingCandidate,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = REPOSITORY_ROOT / "Implementation Docs"
SCHEMA = DOCUMENTS / "02_Architecture_and_Contracts" / "04_Database_Schema.md"

# §12.5's field list, as the document writes it.
SECTION = re.compile(r"## 12\.5 `matching_candidates`\n(.*?)\n## ", re.S)


@pytest.fixture(scope="module")
def section() -> str:
    text = SCHEMA.read_text(encoding="utf-8")
    match = SECTION.search(text)
    assert match is not None, "§12.5 has moved or been retitled; this file reads nothing"
    body = match.group(1)
    assert body.strip(), "§12.5 parsed empty, so every comparison below is vacuous"
    return body


def test_every_field_the_document_lists_is_a_column(section: str) -> None:
    """The document names twelve fields in one sentence; all twelve must exist."""

    listed = re.search(r"Fields: (.+?)\.\n", section)
    assert listed is not None, "§12.5's `Fields:` sentence has changed shape"

    expected = {name.strip().strip("`") for name in listed.group(1).split(",")}
    assert len(expected) >= 10, f"only {len(expected)} fields parsed; the sentence changed"

    actual = set(MatchingCandidate.__table__.columns.keys())
    missing = sorted(expected - actual)

    assert missing == [], f"§12.5 lists these and the table has none of them: {missing}"


def test_the_table_adds_nothing_the_document_does_not_list(section: str) -> None:
    """The other direction, which is the one that catches an invented column.

    M8 slice 2 added `rotation_degrees` to `receipt_segments` against a silent document 04, and
    recorded it as DOC-CONFLICT-057 rather than letting it pass unnoticed. Nothing here needs
    that, and this test is what says so.
    """

    listed = re.search(r"Fields: (.+?)\.\n", section)
    assert listed is not None
    expected = {name.strip().strip("`") for name in listed.group(1).split(",")}

    actual = set(MatchingCandidate.__table__.columns.keys())
    extra = sorted(actual - expected)

    assert extra == [], (
        f"these columns are not in §12.5's field list: {extra}. Adding one is a named deviation "
        "with a conflict id, not a quiet convenience."
    )


def test_the_statuses_are_the_catalogue_five(section: str) -> None:
    """§12.5 restates them, and `status_catalog.yaml` is the authority the CHECK is held to."""

    listed = re.search(r"Statuses: (.+?)\.\n", section)
    assert listed is not None, "§12.5's `Statuses:` sentence has changed shape"

    expected = tuple(name.strip().strip("`") for name in listed.group(1).split(","))
    assert expected == CANDIDATE_STATUSES, (
        f"the document lists {expected} and the model has {CANDIDATE_STATUSES}"
    )


def test_the_unique_is_on_the_pair_and_the_method(section: str) -> None:
    """The third column is load bearing: two methods may suggest one pair."""

    assert "UNIQUE(receipt_segment_id, payment_attempt_id, method)" in section, (
        "§12.5's unique has changed and this test is comparing against a stale expectation"
    )

    uniques = {
        tuple(column.name for column in constraint.columns)
        for constraint in MatchingCandidate.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("receipt_segment_id", "payment_attempt_id", "method") in uniques, uniques


def test_the_score_check_is_the_documented_range(section: str) -> None:
    assert "score >= 0 AND score <= 1" in section, "§12.5's score CHECK has changed"

    checks = " ".join(
        str(constraint.sqltext)
        for constraint in MatchingCandidate.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    )
    assert "score >= 0" in checks and "score <= 1" in checks, checks


def test_acceptance_is_not_terminal_because_document_05_overrides_it() -> None:
    """The correction the first draft of the model needed.

    `05_API_Specification.md:1820` requires a reason when "overriding a previously accepted
    candidate", which only means something if `accepted_for_confirmation` has an arrow out. The
    first `PERMITTED_TRANSITIONS` made it terminal and would have refused an operation the API
    specification describes.
    """

    api = (DOCUMENTS / "02_Architecture_and_Contracts" / "05_API_Specification.md").read_text(
        encoding="utf-8"
    )
    assert "overriding a previously accepted candidate" in api, (
        "document 05 no longer describes an override, so this transition needs re-deciding "
        "rather than keeping on a citation that has gone"
    )

    assert CANDIDATE_REJECTED in PERMITTED_TRANSITIONS[CANDIDATE_ACCEPTED]


def test_every_terminal_status_really_is_terminal() -> None:
    """`rejected`, `superseded` and `expired` have no outgoing arrow.

    Asserted together with the two that do, because a table where *everything* is terminal would
    satisfy this alone while making the whole aggregate unusable.
    """

    for status in (CANDIDATE_REJECTED, CANDIDATE_SUPERSEDED, CANDIDATE_EXPIRED):
        assert PERMITTED_TRANSITIONS[status] == frozenset(), status

    assert PERMITTED_TRANSITIONS[CANDIDATE_PROPOSED], "proposed must be able to move"
    assert PERMITTED_TRANSITIONS[CANDIDATE_ACCEPTED], "accepted must be able to be overridden"


def test_the_transition_table_covers_every_status() -> None:
    """Guard the guard: a status missing from the table is one every transition refuses."""

    assert set(PERMITTED_TRANSITIONS) == set(CANDIDATE_STATUSES)
    for targets in PERMITTED_TRANSITIONS.values():
        assert targets <= set(CANDIDATE_STATUSES), targets
