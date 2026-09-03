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
    ("beneficiaries", "status"): "beneficiary",
    ("payment_requests", "status"): "payment_request",
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
    # M6. All three carry a canonical catalogue set, so the first shape below applies and the
    # CHECK must equal the catalogue exactly.
    #
    # `payment_batches.status` is the interesting one: `status_catalog.yaml:359-370` marks nine
    # of its eleven states `derived: true`, and `04_Database_Schema.md:971` stores the column
    # anyway. It is mapped here rather than parked in DELIBERATELY_UNCONSTRAINED because the
    # catalogue *does* record a canonical set — derived is a statement about where the value
    # comes from, not about whether it is enumerated. What the derivation costs is a second
    # obligation, discharged by the container-projection test in this slice: the stored value
    # cannot disagree with the current version's state, which this gate cannot see. Its id is
    # deliberately not written here — the traceability scanner counts any occurrence in a test
    # file as a discharge, so naming it would let this comment stand in for the assertion.
    ("payment_attempts", "status"): "payment_attempt",
    ("payment_batches", "status"): "payment_batch",
    ("payment_batch_versions", "status"): "payment_batch_version",
    # M7 slice 2. `05_API_Specification.md:536` lists a *different* five states for this column —
    # it has `superseded`, which the catalogue does not, and `failed` where the catalogue says
    # `generation_failed`. That is DOC-CONFLICT-016, and mapping the column here is what settles
    # it without anybody having to arbitrate: this gate holds the CHECK to the aggregate exactly,
    # so the catalogue's eight are what the column permits and document 05 is owed an editorial
    # fix. G-3 records the one substantive part, which is whether an export can be `superseded`
    # at all or whether replacement always voids it.
    ("bank_excel_exports", "status"): "bank_export",
    # M8 slice 1. The catalogue's `bank_result_bundle` aggregate has eight canonical states and
    # records five more — `files_stored`, `normalized`, `under_manual_review`, `needs_attention`,
    # `archived` — as unresolved aliases. Mapping the column is what keeps those five out of the
    # CHECK: this gate holds the constraint to the aggregate exactly, so an alias cannot be
    # admitted by somebody who reads another document and finds the name plausible.
    ("bank_result_bundles", "status"): "bank_result_bundle",
    # M8 slice 2. Seven canonical states; `processing` and `archived` are unresolved aliases in the
    # catalogue and neither is admitted. Q-2 records why a segment awaiting its crop rests in
    # `created` rather than in an invented `processing`: the *job* carries the render's progress.
    ("receipt_segments", "status"): "receipt_segment",
    # M8 slice 3. The only M8 aggregate the catalogue settles completely — four canonical states and
    # no unresolved aliases at all, which after three slices of the opposite is worth noting.
    ("manual_review_tasks", "status"): "manual_review_task",
    # M9 slice 1. Five canonical states, no unresolved aliases, and four of the five terminal —
    # the catalogue settles this aggregate completely. That is M9's pattern rather than its
    # exception: the milestone opened with every status, permission and audit action approved.
    ("matching_candidates", "status"): "matching_candidate",
    # M9 slice 2. Three canonical states, and the aggregate the catalogue itself flags as
    # unsettled: `voided` is recorded there as a **provisional alias** for `revoked`, because
    # documents 04 and 05 spell it one way and 06 and 08 the other. The CHECK admits the canonical
    # three only — this gate holds a constraint to its aggregate exactly, which is what makes the
    # alias a decision somebody records rather than a spelling that leaks into a column.
    ("confirmed_evidence_links", "status"): "confirmed_evidence_link",
    # M9 slice 7. Three canonical states and no aliases, and **two of the three are written by
    # nothing yet**: the projection inserts `unread`, and `read`/`dismissed` belong to a recipient
    # action that has no route. The CHECK lists all three anyway because this gate holds a
    # constraint to its aggregate *exactly* — narrowing it to what one slice happens to use would
    # make the next slice's legitimate value look like drift.
    ("notifications", "status"): "notification",
    # M10 slice 1. Eighteen canonical states, no aliases, nothing unresolved — the catalogue
    # settles this aggregate completely, and its list is `04_Database_Schema.md:711`'s verbatim.
    # Checked value by value before the CHECK was written, because this gate holds a constraint to
    # its aggregate exactly and a mismatch would have failed the migration's own test rather than
    # this one.
    ("gold_sale_orders", "status"): "gold_sale_order",
    # M10 slice 2. Nine canonical states, no aliases. Two of them — `duplicate_suspected` and
    # `superseded` — belong to matching and correction and are unreachable until slices 5 and 8;
    # the CHECK admits all nine anyway, because this gate holds a constraint to its aggregate
    # *exactly* and narrowing it to what one slice uses would make the next slice's legitimate
    # value look like drift.
    ("incoming_payment_receipts", "status"): "incoming_payment_receipt",
    # M10 slice 3. Document 06 §10.1's five, and the catalogue's `bank_statement_file` aggregate
    # carries exactly those with no aliases.
    ("bank_statement_files", "status"): "bank_statement_file",
    # M10 slice 3, and the interesting one. The aggregate's canonical set is document 06 §10.2's
    # five execution states; document 08 §8.3 defines nine, and the six extra sit in the
    # catalogue's **`m0_decisions_required`** section under this aggregate's name, asking M0 to
    # "decide whether parsing execution and accountant import review are separate state axes or one
    # extended lifecycle".
    #
    # So the CHECK carries the five, and that is not the implementation preferring the shorter
    # list: `parsing` and `parse_failed` are recorded in the aggregate as *aliases* of `running`
    # and `failed`, and enforcing an alias would let two spellings of one state coexist. The
    # remaining six describe an accountant reviewing what a parser produced, which is a second axis
    # M0 has not yet approved — and this gate would fail if the slice had invented it.
    ("bank_statement_import_runs", "status"): "bank_statement_import_run",
    # M10 slice 5, and the aggregate is chosen rather than obvious. `status_catalog.yaml` carries
    # **two** for this one table — `incoming_match_candidate` (document 06 §11.1's five states) and
    # `incoming_confirmed_match` (§11.2's three) — because document 04 §10.7 collapses into one
    # table what the outgoing direction splits into `matching_candidates` and
    # `confirmed_evidence_links`.
    #
    # The CHECK enforces the candidate set, exactly, because that is what slice 5 writes: it
    # proposes and rejects, and §21.5 keeps acceptance separate from financial confirmation. Slice
    # 6 inherits the same two-axis question `bank_statement_import_run` above already put to M0 —
    # whether `active/replaced/revoked` becomes a second column or extends this one — and this gate
    # is what will refuse a slice that answers it by widening a CHECK.
    ("incoming_payment_matches", "status"): "incoming_match_candidate",
    # M10 slice 7. Catalogued, and completely: `gold_dispatch` carries all six of document 06
    # section 12.2's states with no unresolved aliases at all — unlike the import run and the
    # match, both of which needed an argument about which aggregate applied. The last table this
    # milestone adds is the one the catalogue had ready.
    ("gold_dispatches", "status"): "gold_dispatch",
}

# Status columns whose value set is **local to one relation** and is not a lifecycle the catalogue
# governs. The opposite case from `DELIBERATELY_UNCONSTRAINED` below: there a governed column ships
# with no CHECK because the values are undecided; here a CHECK exists and there is no aggregate for
# it to answer to.
#
# The distinction is worth keeping because the two failures look identical from the gate and are
# opposite in kind. Every entry carries its reason, and `test_each_local_lifecycle_has_a_reason`
# refuses a bare one — a new unmapped column still fails until somebody says which of the two it is.
LOCAL_LIFECYCLES: dict[tuple[str, str], str] = {
    ("bank_result_bundle_batch_links", "status"): (
        "M8 slice 1. Two values, `active` and `replaced`. `04_Database_Schema.md:1197` gives the "
        "table a `status` and a `replaced_at` and describes replacement in prose at `:1306`; it "
        "names no aggregate, and `status_catalog.yaml` has none. Nothing outside this table "
        "observes the value — it exists so a corrected belief supersedes an earlier one instead of "
        "overwriting it, which is the same shape as `payment_attempt_allocations`' release "
        "columns, a relation document 04 never mentions at all. Adding an aggregate would mean "
        "inventing one for a two-value flag inside approved M0 governance under a checksum chain, "
        "which is not an implementer's decision. Q-8 in the M8 plan records it."
    ),
    ("payment_result_publications", "status"): (
        "M9 slice 5. Three values, `active`, `superseded` and `revoked`, from "
        "`04_Database_Schema.md:1140` — and `status_catalog.yaml` has **no** "
        "`payment_result_publication` aggregate at all, so this CHECK has nothing to be held to "
        "and document 04 is its only source. Unlike the row above this is not a two-value local "
        "flag: it is a real lifecycle that slice 7's correction moves, and the right fix is for "
        "the catalogue to gain the aggregate. Recorded rather than papered over, because adding "
        "one to approved M0 governance under a checksum chain is not an implementer's decision. "
        "G-6 in the M9 plan records it."
    ),
    ("bank_statement_rows", "status"): (
        "M10 slice 4. Five values - valid, warning, invalid, ignored_empty, possible_duplicate - "
        "from `08_Bank_File_and_Result_Processing.md:514`, and `status_catalog.yaml` has "
        "**no** `bank_statement_row` aggregate at all. It is the only M10 table for which that is "
        "true: the plan's first governance survey said three of them had none and the corrected "
        "survey found aggregates for the other two, which is how this entry came to be written "
        "with a reason instead of by habit. "
        "Unlike `bank_result_bundle_batch_links` above this is not a two-value local flag - it is "
        "a real validation lifecycle an approved document enumerates, and the right fix is for the "
        "catalogue to gain the aggregate. Recorded rather than papered over, because adding one to "
        "approved M0 governance under a checksum chain is not an implementer's decision. Section 1 "
        "of the M10 plan records it, and `test_statement_row_shape.py` is what holds the set to "
        "document 08 in the meantime."
    ),
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
    # DOC-CONFLICT-048. The `beneficiary` aggregate covers the lifecycle only, and
    # the four verification values live in a Notes cell of document 04 that no
    # approved catalogue restates. Unlike the entries above, nothing here is
    # *disputed* — the values are perfectly clear. What is missing is approval, and
    # a CHECK is the one way to make an unapproved vocabulary permanent.
    ("beneficiaries", "verification_status"): (
        "beneficiary verification — DOC-CONFLICT-048, no approved aggregate covers it"
    ),
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

    unmapped = sorted(
        set(enforced_status_values()) - set(STATUS_COLUMN_TO_AGGREGATE) - set(LOCAL_LIFECYCLES)
    )

    assert unmapped == [], (
        "these status constraints are not mapped to a catalogue aggregate, so nothing "
        f"checks them against the approved names: {unmapped}. If the column is a lifecycle local "
        "to one relation rather than one the catalogue governs, record it in LOCAL_LIFECYCLES "
        "with the reason."
    )


def test_each_local_lifecycle_has_a_reason() -> None:
    """An exemption with no reason is what the gate above exists to prevent, one level up.

    `LOCAL_LIFECYCLES` subtracts from that assertion, so it is the place an unwanted column would
    be parked. Requiring a substantial reason that cites its authority makes parking one more work
    than mapping it — and a bare entry fails here rather than passing quietly.
    """

    assert LOCAL_LIFECYCLES, "the set is empty; delete it rather than carrying an unused escape"

    for column, reason in LOCAL_LIFECYCLES.items():
        assert len(reason) > 200, f"{column} is exempted with no real reason"
        assert ".md:" in reason, f"{column} is exempted and cites no document line"


def test_no_column_is_both_mapped_and_exempted() -> None:
    """The two dictionaries must not overlap, or one of them is a lie.

    A column in both would be mapped to an aggregate *and* declared to have none, and the
    subtraction above would hide the contradiction — the gate would pass while the file disagreed
    with itself.
    """

    both = sorted(set(STATUS_COLUMN_TO_AGGREGATE) & set(LOCAL_LIFECYCLES))

    assert both == [], f"these columns are both mapped and exempted: {both}"


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
