"""What the evidence surface is, and — mostly — what it is not.

M8 slice 2. Two of this slice's five obligations changed shape while it was being built, and this
file is where that is recorded rather than quietly absorbed.

The plan expected a guarded `PATCH /receipt-segments/{id}`, with the finalization rule
`05_API_Specification.md:1795` states. `permission_catalog.yaml` settles it the other way in terms:
`receipt_segment.update` carries `status: unresolved_no_exact_canonical_target` and
`resolution: deny until an explicitly scoped pre-finalization update permission is approved`, and
`m0_open_items` carries `receipt_segment_update_permission` with
`conservative_effect: deny_update_until_action-specific_permission_is_approved` — citing the same
document 05 lines the plan read.

So `SVC-SEGMENT-001` and `SVC-SEGMENT-002` are **absences**: the route does not exist, and no route
that does exist can write provenance. Asserted over the live route table rather than by reading one
module, because the next person to find that endpoint in document 05 will wonder where it went, and
the answer has to be somewhere a test can fail.

Covers: DB-SEGMENT-002, SVC-SEGMENT-001, SVC-SEGMENT-002.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GOVERNANCE = REPOSITORY_ROOT / "docs" / "governance"
SCHEMA = (
    REPOSITORY_ROOT
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "04_Database_Schema.md"
)

# Provenance: what the row says about where the evidence came from. None of it is writable, at any
# status, by any route — `20260824_0024` grants UPDATE on none of these.
PROVENANCE_COLUMNS = frozenset(
    {
        "source_file_id",
        "bank_result_bundle_file_id",
        "page_number",
        "bbox_x",
        "bbox_y",
        "bbox_width",
        "bbox_height",
        "rotation_degrees",
        "source_pixel_width",
        "source_pixel_height",
        "renderer_version",
        "creation_method",
        "created_by_actor_type",
        "created_by_actor_id",
    }
)


def routes() -> list[tuple[str, str]]:
    """Every `/api/v1` route the router serves, as (method, path).

    Walks the router rather than building the app: `create_app()` reads `Settings`, so a structural
    test would need a database URL to answer a question that has nothing to do with one. The walk
    accumulates `include_context.prefix` because this FastAPI version wraps each `include_router`
    call in a node whose own `path` is `None` — the same walk
    `tests/backend/test_m3_definition_of_done.py` documents, and duplicated for the reason it gives:
    a shared helper in a third file is a third thing to keep working.
    """

    from app.api.router import api_v1_router

    found: list[tuple[str, str]] = []
    seen: set[int] = set()

    def walk(node: object, prefix: str) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))

        context = getattr(node, "include_context", None)
        nested_prefix = prefix + (getattr(context, "prefix", "") or "")

        nested = getattr(node, "original_router", None)
        if nested is not None:
            walk(nested, nested_prefix)
        for child in getattr(node, "routes", []) or []:
            walk(child, nested_prefix)

        path = getattr(node, "path", None)
        methods = getattr(node, "methods", None) or set()
        if not path:
            return
        full = path if path.startswith("/api/v1") else f"{nested_prefix}{path}"
        for method in sorted(methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.append((method, full))

    walk(api_v1_router, "")
    return found


def test_the_route_table_is_not_empty() -> None:
    """Guard the guard. Every absence below is vacuous over an empty list."""

    assert len(routes()) > 30
    assert any(path.endswith("/receipt-segments/{segment_id}") for _method, path in routes())


def test_no_route_can_patch_a_segment() -> None:
    """`SVC-SEGMENT-001`, reshaped into the absence the permission catalogue requires.

    Document 05 defines `PATCH /api/v1/receipt-segments/{segment_id}` at `:1792`. It is not served,
    and it must not be until an explicitly scoped permission is approved — the catalogue's own
    resolution, not this slice's preference.

    Asserted over every method on every path rather than over the one module, because the mutation
    could arrive anywhere: a `PUT` on the same path, or a `POST .../correct` beside it.
    """

    offending = [
        (method, path)
        for method, path in routes()
        if "receipt-segment" in path and method in {"PATCH", "PUT", "DELETE"}
    ]

    assert offending == [], (
        "these routes mutate a segment, and `permission_catalog.yaml` resolves "
        "`receipt_segment.update` as deny-until-approved with `canonical_targets: []`: "
        f"{offending}"
    )


def test_the_permission_catalogue_still_refuses_that_permission() -> None:
    """The other half, and the half that expires.

    The absence above is only correct while the catalogue still refuses. When M0 approves a scoped
    update permission this test fails — which is the point: it is the notification that
    `SVC-SEGMENT-001` may become a positive obligation again, rather than a silence that outlives
    its reason.
    """

    import yaml

    catalogue = yaml.safe_load((GOVERNANCE / "permission_catalog.yaml").read_text(encoding="utf-8"))
    text = (GOVERNANCE / "permission_catalog.yaml").read_text(encoding="utf-8")

    assert "receipt_segment.update" in text
    block = text[text.index("receipt_segment.update:") :][:400]
    assert "unresolved_no_exact_canonical_target" in block, (
        "receipt_segment.update is no longer unresolved. If M0 approved a scoped permission, "
        "slice 2's PATCH absence can be revisited and this test replaced."
    )
    assert "canonical_targets: []" in block
    assert catalogue is not None


def test_no_route_accepts_a_provenance_field() -> None:
    """`SVC-SEGMENT-002`. Nothing on the surface can rewrite where evidence came from.

    Checked against the request models rather than the database grants, because the two answer
    different questions: the grant makes the write impossible, and this makes the *attempt*
    impossible to express. A field accepted and silently ignored is the version that looks like it
    works.

    The creation request is exempt for the four fields it legitimately sets at insert — a segment
    has to say which file and which page it came from — and the exemption is named rather than
    inferred, so a fifth appearing is a failure.
    """

    from app.api.v1 import receipt_segments as module

    settable_at_creation = {
        "source_file_id",
        "bank_result_bundle_file_id",
        "page_number",
        # Not provenance the caller supplies: `attach_external` writes 0 and the
        # `rotation_needs_a_rectangle` CHECK refuses anything else without a rectangle.
    }

    for name in ("ManualFieldsRequest", "AttachExternalRequest"):
        model = getattr(module, name)
        offending = sorted(
            (set(model.model_fields) & PROVENANCE_COLUMNS) - settable_at_creation
        )
        assert offending == [], f"{name} accepts provenance it must not: {offending}"


def test_the_creation_request_cannot_supply_a_rectangle() -> None:
    """The sharper half of the same claim.

    `manual_external_attachment` attaches a whole file, so there is no rectangle to send — and if
    the request could carry one, the crop route slice 4 builds would have a second, unguarded
    entrance. §12.4's bbox CHECK would still hold, which is exactly the problem: a valid rectangle
    with no renderer behind it produces a segment claiming a crop that was never rendered.
    """

    from app.api.v1.receipt_segments import AttachExternalRequest

    fields = set(AttachExternalRequest.model_fields)
    for forbidden in ("bbox", "bbox_x", "rotation_degrees", "renderer_version", "segment_file_id"):
        assert forbidden not in fields, f"the external route accepts {forbidden}"


def test_the_five_creation_methods_are_the_documents(  ) -> None:
    """`DB-SEGMENT-002`, first half: the vocabulary is §12.4's, parsed from the document.

    `:1249` gives the five in a fenced block. Parsed rather than transcribed for the reason M5's
    wrong type behind a green test established: a hand-copied list agrees with the code that copied
    it.
    """

    from app.db.models.receipt_segment import CREATION_METHODS

    text = SCHEMA.read_text(encoding="utf-8")
    start = text.index("Creation methods:")
    block = text[start:]
    fenced = block[block.index("```text") + 7 : block.index("```", block.index("```text") + 7)]
    documented = [line.strip() for line in fenced.splitlines() if line.strip()]

    assert len(documented) == 5, documented
    assert list(CREATION_METHODS) == documented


def test_the_ai_creation_method_is_unreachable() -> None:
    """`DB-SEGMENT-002`, second half, and the one that matters.

    `04_Database_Schema.md:1259` keeps `ai_auto_segmentation` feature-flagged for later phases. It
    is in the CHECK — the column must be able to hold it when a later phase writes it — and no code
    path this milestone adds can produce it. An enum value with a writer nobody meant is how a
    feature flag gets bypassed.

    Asserted over the whole command and API surface by grep, deliberately blunt: the value is a
    string, and a module that mentions it at all is a module worth looking at.
    """

    surface = []
    for directory in ("app/commands", "app/api"):
        for path in (REPOSITORY_ROOT / "services" / "backend" / directory).rglob("*.py"):
            surface.append((path, path.read_text(encoding="utf-8")))

    assert surface, "found no command or API modules; the assertion below would be vacuous"

    offending = [
        str(path.relative_to(REPOSITORY_ROOT))
        for path, text in surface
        if "ai_auto_segmentation" in text
    ]

    assert offending == [], (
        f"these modules name the AI segmentation method, which is feature-flagged: {offending}"
    )


def test_the_status_vocabulary_matches_the_catalogue() -> None:
    """The segment's seven, from `status_catalog.yaml` rather than from document 04.

    Document 04 names no status set for this table. `test_status_catalogue_drift.py` holds the CHECK
    to the aggregate; this holds the Python constant to the same source, so the two cannot drift
    apart between them.
    """

    import yaml
    from app.db.models.receipt_segment import RESOLVED_SEGMENT_STATUSES, SEGMENT_STATUSES

    catalogue = yaml.safe_load((GOVERNANCE / "status_catalog.yaml").read_text(encoding="utf-8"))
    aggregates = catalogue.get("aggregates", catalogue)
    canonical = [state["canonical"] for state in aggregates["receipt_segment"]["states"]]

    assert list(SEGMENT_STATUSES) == canonical
    # Every "resolved" status is a real one. A typo here would silently count nothing as resolved,
    # which would leave every bundle uncloseable and look like a workflow problem.
    assert set(RESOLVED_SEGMENT_STATUSES) <= set(canonical)
    # And the queue statuses are the complement, so `close_bundle`'s refusal covers exactly the
    # segments that still need a person.
    assert set(canonical) - set(RESOLVED_SEGMENT_STATUSES) == {
        "created",
        "unmatched",
        "candidate_found",
    }


def test_the_index_predicate_keeps_the_documents_wording() -> None:
    """Q-10, pinned so the divergence cannot be quietly tidied away.

    `04_Database_Schema.md:1672` writes the partial predicate as
    `status IN ('unmatched','candidate_found','needs_review')`, and `needs_review` is not a
    `receipt_segment` state in `status_catalog.yaml` — not canonical and not even an unresolved
    alias — so `ck_receipt_segments_status_value` makes that disjunct unreachable.

    The predicate is copied anyway. Trimming it would make the index a differently-scoped object
    wearing the document's name, which
    `tests/integration/test_schema_matches_the_specification.py` refuses in those words. This test
    exists so that whoever resolves the disagreement has to come here and delete it.
    """

    from app.db.models.receipt_segment import ReceiptSegment

    predicates = [
        str(index.dialect_options["postgresql"].get("where"))
        for index in ReceiptSegment.__table__.indexes
        if index.name == "idx_segment_match_amount_iban"
    ]

    assert predicates, "the documented partial index is gone"
    assert "needs_review" in predicates[0], (
        "the index predicate no longer matches document 04. If M0 corrected the document or added "
        "the state, delete this test and the Q-10 row."
    )


@pytest.mark.parametrize(
    "constraint",
    [
        "bbox_normalized_or_absent",
        "bbox_is_all_or_nothing",
        "rotation_is_a_right_angle",
        "rectangle_needs_a_page",
        "rotation_needs_a_rectangle",
    ],
)
def test_each_reproduction_constraint_exists(constraint: str) -> None:
    """The four constraints that make a segment rebuildable, named one per test.

    Their behaviour at each edge is `tests/integration/test_segment_intake.py`'s — a CHECK can only
    be shown to refuse by asking PostgreSQL to refuse. This asserts they are *present*, which is
    the claim that would silently vanish in a refactor of `__table_args__`.

    Three of the five are not in §12.4. A rectangle without its page reproduces nothing and a
    rotation without a rectangle describes nothing — DOC-CONFLICT-057 explains why the angle is
    there at all. `bbox_is_all_or_nothing` is the interesting one: **§12.4's own CHECK accepts three
    coordinates and a NULL fourth**, because its in-bounds branch evaluates to NULL and a CHECK
    rejects only on false. Q-11, found by testing the documented constraint at its edges rather than
    trusting it.
    """

    from app.db.models.receipt_segment import ReceiptSegment

    names = {
        check.name
        for check in ReceiptSegment.__table__.constraints
        if check.__class__.__name__ == "CheckConstraint"
    }

    assert any(name and re.search(rf"{constraint}$", name) for name in names), sorted(
        name for name in names if name
    )
