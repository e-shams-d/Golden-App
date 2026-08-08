"""Every status value the database enforces must trace to the approved catalogue.

`status_catalog.yaml` is `approved_phase_1a`. That is what makes this gate legitimate:
a CI gate may only be written against an approved catalogue, because a gate is a
decision made mandatory, and enforcing an unapproved one would decide a question
nobody has answered. The other three machine-readable catalogues remain
`provisional_pending_m0_approval` and are deliberately **not** gated here —
`docs/governance/README.md` records which is which.

Without this, an approved status name and the value the database actually persists
diverge in silence. Nothing else would notice: the CHECK constraint accepts whatever
it was written with, the ORM round-trips it, and the mismatch surfaces when a
milestone that reads the catalogue meets rows that do not match it.

Three shapes are covered, and the third is the one that needs care:

**A canonical set.** The code's values must equal it exactly — not a subset. A
missing value means a state the workflow defines cannot be reached; an extra one
means a state no document defines.

**No canonical set, with a deliberate deviation.** `file_object` is recorded
`canonical: null` with eight aliases, and `20260801_0011` permits seven. That gap is
approved and recorded as a conflict row, so the test requires the row to exist rather
than accepting the gap on its own. An undocumented gap and a documented one look
identical in the schema.

**No canonical set, and no CHECK.** `identity_account`, `bank_profile_version`,
`bank_mapping` and `idempotency_record` ship with no value constraint on purpose:
enumerating them from a migration would resolve a question the catalogue reserves.
That absence is pinned, because the tempting fix for any future status bug is to add
the enum.

Covers: CI-DRIFT-001, CI-DRIFT-002.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
import pytest
import yaml
from app.db.base import Base

GOVERNANCE = Path(__file__).resolve().parents[2] / "docs" / "governance"
CATALOGUE = GOVERNANCE / "status_catalog.yaml"
REGISTER = GOVERNANCE / "CONFLICT_REGISTER.md"

# Which mapped column carries which catalogue aggregate's state. Written out rather
# than inferred from the table name: `file_objects.storage_status` is the
# `file_object` aggregate, and a convention that guessed that would guess wrong
# somewhere else. An unmapped status CHECK fails the first test below.
STATUS_COLUMN_TO_AGGREGATE: dict[tuple[str, str], str] = {
    ("outbox_events", "status"): "outbox_event",
    ("processing_jobs", "status"): "processing_job",
    ("file_objects", "storage_status"): "file_object",
    # Both identity tables carry the same aggregate: the login account is one
    # lifecycle whether the human is staff or a trader contact. Moved here from
    # DELIBERATELY_UNCONSTRAINED by 20260808_0013 when DOC-CONFLICT-037 was
    # decided; the three names the catalogue records and the schema refuses are
    # listed in APPROVED_OMISSIONS below.
    ("admin_users", "status"): "identity_account",
    ("trader_users", "status"): "identity_account",
}

# Columns whose aggregate the catalogue records with `canonical: null`, and which
# therefore ship with no value CHECK at all. Listed with the reason so the next
# person to reach for an enum finds the reason before the constraint.
DELIBERATELY_UNCONSTRAINED: dict[tuple[str, str], str] = {
    # The catalogue holds one `trader` aggregate carrying document 06's single
    # five-state machine, plus `blocked` and `approved` as unresolved aliases it
    # says in terms must not be collapsed without policy approval. Document 04
    # splits the same idea across two columns whose values do not partition that
    # set. Enumerating either here would answer, from a migration, whether
    # `blocked` folds into `suspended` and whether `approved` maps to `active` —
    # which DOC-CONFLICT-024 assigns to M5's trader lifecycle. M3 decides the
    # structure (three axes, no stored projection), not the values.
    ("traders", "operational_status"): "trader — DOC-CONFLICT-024 values are M5",
    ("traders", "approval_status"): "trader — DOC-CONFLICT-024 values are M5",
    ("bank_profile_versions", "status"): "bank_profile_version — catalogue records canonical: null",
    ("bank_mappings", "status"): "bank_mapping — catalogue records canonical: null",
    ("idempotency_records", "status"): "idempotency_record — catalogue records canonical: null",
    # Both Open under DOC-CONFLICT-029 and ADR-008; the availability gate constrains
    # the consequence instead. See tests/backend/test_reserved_scan_status.py.
    ("file_objects", "scan_status"): "scan outcomes — DOC-CONFLICT-029 and ADR-008 are Open",
}

# A value the catalogue records that the schema deliberately does not permit, and the
# conflict row that authorises the narrowing. Named by id rather than matched by
# keyword: a citation must point at a row that exists, and a keyword match cannot tell
# DOC-CONFLICT-036 from a renumbered DOC-CONFLICT-136.
APPROVED_OMISSIONS: dict[tuple[str, str], str] = {
    ("file_object", "deleted_by_policy"): "DOC-CONFLICT-036",
    # The three names DOC-CONFLICT-037 refuses. The catalogue keeps recording all
    # seven because seven is what the documents say; the schema permits four. Each
    # rejection is a value the register's row must name, which is what makes the
    # reason reviewable rather than a comment in a migration nobody re-reads.
    ("identity_account", "locked"): "DOC-CONFLICT-037",
    ("identity_account", "pending"): "DOC-CONFLICT-037",
    ("identity_account", "inactive"): "DOC-CONFLICT-037",
}

_IN_CLAUSE = re.compile(r"^\s*(\w+)\s+IN\s*\((.*)\)\s*$", re.S)


@pytest.fixture(scope="module")
def catalogue() -> dict[str, Any]:
    document = yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))
    assert document["catalog_status"] == "approved_phase_1a", (
        "this gate may only run against an approved catalogue; "
        f"status_catalog.yaml is {document['catalog_status']!r}"
    )
    return document


def canonical_states(catalogue: dict[str, Any], aggregate: str) -> set[str] | None:
    entry = catalogue["aggregates"].get(aggregate)
    if entry is None:
        return None
    return {state["canonical"] for state in entry["states"]}


def recorded_aliases(catalogue: dict[str, Any], aggregate: str) -> set[str] | None:
    for entry in catalogue["status_sets_without_document_06_canonical"]:
        if entry["aggregate"] == aggregate:
            return set(entry["aliases"])
    return None


def enforced_status_values() -> dict[tuple[str, str], set[str]]:
    """Every `column IN (...)` CHECK on a status-ish column, read from the metadata.

    Read from `Base.metadata` rather than by parsing migrations: the models are what
    autogenerate compares against, and `test_schema_matches_models.py` already
    requires the two to agree.
    """

    found: dict[tuple[str, str], set[str]] = {}
    for table_name, table in sorted(Base.metadata.tables.items()):
        for constraint in table.constraints:
            if constraint.__class__.__name__ != "CheckConstraint":
                continue
            match = _IN_CLAUSE.match(str(constraint.sqltext))
            if not match or "status" not in match.group(1):
                continue
            values = {value.strip().strip("'") for value in match.group(2).split(",")}
            found[(table_name, match.group(1))] = values
    return found


def test_every_enforced_status_set_is_mapped_to_an_aggregate() -> None:
    """An unmapped status CHECK is one nothing compares against.

    This is the test that keeps the gate honest as tables arrive: a new status column
    fails here until somebody says which aggregate it belongs to, rather than being
    silently exempt.
    """

    unmapped = sorted(set(enforced_status_values()) - set(STATUS_COLUMN_TO_AGGREGATE))

    assert unmapped == [], (
        "these status constraints are not mapped to a catalogue aggregate, so nothing "
        f"checks them against the approved names: {unmapped}"
    )


def test_the_mapping_does_not_name_a_column_that_no_longer_exists() -> None:
    """Guard the guard: a stale mapping entry makes a test pass by describing nothing."""

    enforced = enforced_status_values()
    stale = sorted(key for key in STATUS_COLUMN_TO_AGGREGATE if key not in enforced)

    assert stale == [], f"mapped columns that carry no status CHECK any more: {stale}"


@pytest.mark.parametrize(
    ("column", "aggregate"),
    sorted(STATUS_COLUMN_TO_AGGREGATE.items()),
    ids=lambda value: value if isinstance(value, str) else ".".join(value),
)
def test_enforced_values_match_the_catalogue(
    catalogue: dict[str, Any], column: tuple[str, str], aggregate: str
) -> None:
    enforced = enforced_status_values()[column]
    canonical = canonical_states(catalogue, aggregate)

    if canonical is not None:
        assert enforced == canonical, (
            f"{'.'.join(column)} enforces {sorted(enforced)}; the approved catalogue's "
            f"canonical set for {aggregate} is {sorted(canonical)}. Extra values are "
            "states no document defines; missing ones are states the workflow defines "
            "and the database refuses."
        )
        return

    aliases = recorded_aliases(catalogue, aggregate)
    assert aliases is not None, f"{aggregate} appears in neither catalogue section"
    assert enforced <= aliases, (
        f"{'.'.join(column)} enforces {sorted(enforced - aliases)}, which the catalogue "
        f"does not record for {aggregate}"
    )


def test_a_deliberate_omission_is_recorded_as_a_conflict(catalogue: dict[str, Any]) -> None:
    """A documented gap and an undocumented one look identical in the schema.

    `file_objects.storage_status` permits seven of the catalogue's eight spellings.
    That is approved and recorded, and this requires the **named** row to exist and be
    Resolved.

    Naming the id is the point, and a negative control is why. An earlier version
    accepted any row mentioning both the aggregate and the omitted value, so
    renumbering the row from 036 to 136 left the gate green — a citation pointing at a
    row that no longer exists is precisely the failure part A of this slice was about.
    """

    register = REGISTER.read_text(encoding="utf-8")
    enforced = enforced_status_values()

    for column, aggregate in sorted(STATUS_COLUMN_TO_AGGREGATE.items()):
        aliases = recorded_aliases(catalogue, aggregate)
        if aliases is None:
            continue
        for value in sorted(aliases - enforced[column]):
            conflict_id = APPROVED_OMISSIONS.get((aggregate, value))
            assert conflict_id is not None, (
                f"{'.'.join(column)} omits {value!r} from the catalogue's recorded set "
                f"for {aggregate}, and no approved conflict authorises the narrowing. "
                "Add the decision to the register and name it here."
            )
            row = next(
                (line for line in register.splitlines() if line.startswith(f"| {conflict_id} |")),
                None,
            )
            assert row is not None, (
                f"{conflict_id} authorises omitting {value!r} but no such row exists in "
                "the register"
            )
            status = [cell.strip() for cell in row.split("|") if cell.strip()][-1]
            assert status.startswith("Resolved"), (
                f"{conflict_id} authorises omitting {value!r} but reads {status!r}, so "
                "the schema is enforcing an undecided narrowing"
            )
            # As a delimited token, not a substring. A bare `value in row` reads
            # `locked` out of `locked_until` and `pending` out of `pending_approval`,
            # so a row could authorise refusing a value while never discussing it —
            # which a negative control demonstrated on exactly those two names.
            assert re.search(rf"(?<![a-z_]){re.escape(value)}(?![a-z_])", row), (
                f"{conflict_id} is cited for the {value!r} omission but does not mention it "
                "as a word of its own"
            )


def test_every_approved_omission_is_still_an_omission(catalogue: dict[str, Any]) -> None:
    """Guard the guard, in the other direction.

    An entry in `APPROVED_OMISSIONS` for a value the schema now permits is a licence
    nobody is using — and it would silently authorise re-narrowing later without a
    fresh decision.
    """

    enforced = enforced_status_values()
    by_aggregate = {
        aggregate: enforced[column] for column, aggregate in STATUS_COLUMN_TO_AGGREGATE.items()
    }

    stale = [
        f"{aggregate}.{value} ({conflict_id})"
        for (aggregate, value), conflict_id in sorted(APPROVED_OMISSIONS.items())
        if value in by_aggregate.get(aggregate, set())
    ]

    assert stale == [], f"approved omissions that are no longer omitted: {stale}"


@pytest.mark.parametrize(
    ("column", "reason"),
    sorted(DELIBERATELY_UNCONSTRAINED.items()),
    ids=lambda value: value if isinstance(value, str) else ".".join(value),
)
def test_a_reserved_status_column_carries_no_value_check(
    column: tuple[str, str], reason: str
) -> None:
    """The absences, pinned.

    Each of these columns belongs to an aggregate the catalogue records without a
    canonical set. Adding the enum would resolve the open question from a migration,
    which is the one thing a migration must never do — it cannot be edited afterwards.
    """

    assert column not in enforced_status_values(), (
        f"{'.'.join(column)} has acquired a value CHECK. It must not have one: {reason}."
    )


def test_the_reserved_list_names_only_columns_that_exist() -> None:
    """Guard the guard: a typo in the list above would assert nothing, forever."""

    missing = sorted(
        f"{table}.{column}"
        for table, column in DELIBERATELY_UNCONSTRAINED
        if table not in Base.metadata.tables or column not in Base.metadata.tables[table].columns
    )

    assert missing == [], f"the reserved list names columns that do not exist: {missing}"


def test_no_enforced_value_is_a_legacy_alias(catalogue: dict[str, Any]) -> None:
    """Document 06 wins every naming conflict, and the PRD spellings are aliases.

    The catalogue's approval scope says a legacy alias "must never be implemented as
    API or database values". A CHECK containing one would persist the spelling the
    approval rejected.
    """

    offenders: list[str] = []
    enforced = enforced_status_values()
    for column, aggregate in sorted(STATUS_COLUMN_TO_AGGREGATE.items()):
        entry = catalogue["aggregates"].get(aggregate)
        if entry is None:
            continue
        aliases = {alias for state in entry["states"] for alias in state.get("aliases", [])}
        for value in sorted(enforced[column] & aliases):
            offenders.append(f"{'.'.join(column)} persists the legacy alias {value!r}")

    assert offenders == [], "\n".join(offenders)
