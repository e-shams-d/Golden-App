"""What M8 must not have built, asserted over the whole surface.

M8 slice 7. Two obligations, and both are absences — which is why neither can be a behavioural test.

`SVC-PRIVACY-002`: no route this milestone adds may mark a segment publishable. A test that
exercised a route and found publication absent would prove it of that route; the claim is about
every route, including the one somebody adds under pressure behind a condition no test reaches.

`TRACE-M8-003`: no AI path is reachable. `04_Database_Schema.md:1259` makes `manual_in_panel_crop`
Phase 1A and keeps `ai_auto_segmentation` feature-flagged; doc 05 `:1721` defines an `ai-extraction`
route this plan does not build. So the assertion is that the route table has no such operation, that
nothing writes the AI creation method, and that the AI usage table stays empty.

**Read against the generated contract and the route table, not against a list written here.** A
hand-copied route list is a second source of truth that goes stale silently — the point of both
assertions is that they see what is actually served.

Covers: SVC-PRIVACY-002, TRACE-M8-003.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from app.db.models.receipt_segment import METHOD_AI, SEGMENT_STATUSES

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPOSITORY_ROOT / "services" / "backend"
CONTRACT = BACKEND / "openapi" / "v1.json"
COMMANDS = BACKEND / "app" / "commands"
API = BACKEND / "app" / "api" / "v1"

# The modules allowed to write a publication field. `payment_publication.py` arrived with M9 slice
# 5 and `publication_correction.py` with 7B — and the second was **found by this gate**, which
# refused it until it was named here.
#
# The exemption is not "these files are trusted": every one of them must call
# `privacy_verification`, and `test_the_allowed_writers_really_verify` is what makes that a
# condition of being on the list rather than a comment beside it. §16.5 applies to a corrected
# publication exactly as it does to a first one — arguably more, since the evidence is new and the
# trader has already been told something.
PUBLICATION_COMMANDS = (
    COMMANDS / "payment_publication.py",
    COMMANDS / "publication_correction.py",
)


def served_routes() -> list[tuple[str, str]]:
    """Every `/api/v1` route the router serves, as (method, path).

    **Walks the router rather than building the app**, which is slice 2's solution to the same
    problem: `create_app()` reads `Settings`, so a structural test would need a database URL, a
    Redis URL and a storage root to answer a question that has nothing to do with any of them. The
    first version of this file called `create_app()` and failed on three missing settings.

    The walk accumulates `include_context.prefix` because this FastAPI version wraps each
    `include_router` call in a node whose own `path` is `None`. Duplicated from
    `test_segment_surface.py` for the reason that file gives: a shared helper in a third place is a
    third thing to keep working.
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
    assert found, "the router walk found no routes, so every assertion below would be vacuous"
    return found


def python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _model_names(tree: ast.Module) -> set[str]:
    """Every name this module imports from `app.db.models`.

    Used to tell a row from a response. Both are built with keyword arguments and only one of
    them writes anything a trader will later be shown.
    """

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "app.db.models"
        ):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def assigned_attributes(path: Path) -> set[str]:
    """Every attribute this module assigns to on a database row.

    Parsed rather than grepped. A grep for `published` matches this file's own docstring and the
    comment in `receipt_segment.py` explaining that M9 owns the state — the seventh and eighth times
    a scan here would have been defeated by the prose written to justify it.

    **Keyword arguments count only when the call constructs an ORM model.** They used to count on
    every call, which was right while nothing could publish and wrong the moment something could:
    M9 slice 5's router builds a `PublicationResponse(published_at=...)` from a row it has just
    read, and that is a render, not a write. Excusing the whole router would have excused the one
    place a leak is most likely to be added, so the *rule* narrowed instead of the file list —
    the same move M6's lineage scan made when a retry legitimately wrote a lineage column.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    models = _model_names(tree)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    names.add(target.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            names.add(node.target.attr)
        elif isinstance(node, ast.Call):
            callee = node.func
            callee_name = (
                callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", None)
            )
            if callee_name in models:
                names.update(keyword.arg for keyword in node.keywords if keyword.arg)
    return names


class TestNothingCanPublish:
    """`SVC-PRIVACY-002`. §16.5: no evidence reaches a trader without a privacy verification.

    **The claim these tests make has changed shape; the obligation has not.** M8 wrote them when
    publication did not exist, so the strongest available form of "nothing publishes without a
    privacy check" was "nothing publishes at all" — §2.5 of the M8 plan, in as many words:
    "publication is M9's, and M8 adds no way round it."

    M9 slice 5 is that milestone. There is now exactly one publication path and it calls
    `privacy_verification` — the guard `app/commands/manual_review_task.py` was built for and could
    not have, its docstring saying so directly: "There is deliberately no setter... a guard on a
    path that does not exist would be untestable."

    So these move from counting paths to checking the one that exists. The failure prevented is the
    same, and it is now the realistic one: a *second* publication path added later that skips the
    check. The class name is kept because the obligation id is, and renaming it would suggest a
    different claim rather than the same one at a later date.
    """

    def test_every_publication_route_goes_through_the_privacy_guard(self) -> None:
        # The whole route table, not a sample. `publications` is doc 05 `:1874`'s path segment and
        # `publishable` is the flag a shortcut would invent.
        publishing = [
            (method, path)
            for method, path in served_routes()
            if "publication" in path or "publishable" in path or "publish" in path
        ]

        # The vacuity control, inline. If this list were empty the assertion below would hold over
        # nothing — before M9 slice 5 that was the correct state and this class asserted it.
        assert publishing, (
            "no publication route is served at all. That was right until M9 slice 5; now it means "
            "the routes were removed or renamed, and this test must follow them rather than pass "
            "by default."
        )

        # Either the check itself or slice 5's wrapper around it. The correction calls
        # `_refuse_unverified_privacy` rather than `privacy_verification` directly, and that is
        # the better of the two: a second copy of the guard is a second thing that can drift from
        # §16.5. What the gate cares about is that the enforcement is reached, not which name
        # reaches it.
        enforcers = ("privacy_verification(", "_refuse_unverified_privacy(")
        for module in PUBLICATION_COMMANDS:
            source = module.read_text(encoding="utf-8")
            assert any(name in source for name in enforcers), (
                f"{module.name} reaches neither {' nor '.join(enforcers)}, so the routes "
                f"{publishing} can put evidence in front of a trader that nobody reviewed. §16.5 "
                "requires the check and `08_Bank_File_and_Result_Processing.md:1314` lists 'no "
                "unresolved privacy warning exists' among the eight publication guards."
            )

    def test_only_the_publication_command_assigns_a_publication_field(self) -> None:
        # **Assignment, not mention.** The forbidden thing is *setting* publishability somewhere
        # that has not been through the guard, and the segment status tuple legitimately contains
        # `published` because M9 uses it. So this looks for writes, and allows exactly one module.
        forbidden = {"published", "publishable", "is_published", "published_at", "publication_id"}

        offenders: dict[str, list[str]] = {}
        for path in [*python_sources(COMMANDS), *python_sources(API)]:
            if path in PUBLICATION_COMMANDS:
                continue
            written = assigned_attributes(path) & forbidden
            if written:
                offenders[str(path.relative_to(BACKEND))] = sorted(written)

        assert offenders == {}, (
            f"something outside the publication command writes a publication field: {offenders}. "
            "Only `app/commands/payment_publication.py` performs the §16.5 verification, so a "
            "writer anywhere else publishes without one."
        )

    def test_the_allowed_writers_really_write_so_the_exemption_is_not_a_hole(self) -> None:
        # The exemption above names files. If one stopped writing these fields the exemption would
        # stand open onto nothing, and the next module to write one would only have to be added
        # beside it.
        for module in PUBLICATION_COMMANDS:
            assert module.exists(), f"{module} is gone"
            written = assigned_attributes(module) & {
                "published",
                "published_at",
                "published_to_trader_at",
            }
            assert written, (
                f"{module.name} writes none of the publication fields, so the exemption excuses a "
                "module that does nothing and the scan protects less than it appears to."
            )

    def test_the_forbidden_state_is_real_so_the_test_is_not_vacuous(self) -> None:
        # The control. If `published` were not a state this schema has, the assertions above would
        # forbid nothing — the third meaning of NOT CAUGHT, arriving in a test rather than in a
        # control.
        assert "published" in SEGMENT_STATUSES

    def test_the_privacy_state_is_readable_so_m9_has_something_to_read(self) -> None:
        # The other half of §2.5: M8 records the verification and M9 reads it. If nothing exposed
        # it, the record would be a mechanism with no caller — which this plan refused twice.
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        segment = contract["components"]["schemas"]["SegmentDetail"]["properties"]

        for field in ("privacy_verified", "privacy_verified_at", "privacy_review_task_id"):
            assert field in segment, f"{field} is not in the contract, so no consumer can read it"


class TestNoAiPathIsReachable:
    """`TRACE-M8-003`. doc 04 `:1259` keeps AI segmentation feature-flagged; this is what that means
    in a running application."""

    def test_the_ai_extraction_route_is_absent(self) -> None:
        # doc 05 `:1721` defines it. §1.4 of the M8 plan says this milestone does not add it, and an
        # absence recorded in a plan is worth exactly as much as a test over the served routes.
        offenders = [
            (method, path) for method, path in served_routes() if "ai-extraction" in path
        ]

        assert offenders == [], f"an AI extraction route is served: {offenders}"

    def test_no_code_writes_the_ai_creation_method(self) -> None:
        # `ai_auto_segmentation` is in `SEGMENT_STATUSES`' sibling tuple because `04_Database_Schema
        # .md:1259` lists it — the CHECK admits it and no writer may use it. Searched over string
        # literals in the AST rather than raw text, because the constant's own definition and the
        # comment above it both contain the word.
        offenders: dict[str, int] = {}
        for path in [*python_sources(COMMANDS), *python_sources(API)]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            literals = sum(
                1
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and node.value == METHOD_AI
            )
            if literals:
                offenders[str(path.relative_to(BACKEND))] = literals

        assert offenders == {}, (
            f"the AI creation method appears as a literal in application code: {offenders}"
        )

    def test_the_method_is_admitted_by_the_schema_so_the_test_bites(self) -> None:
        # The control again, and it is not decoration: if `ai_auto_segmentation` were not a
        # permitted creation method, "no code writes it" would be true of a value nothing could
        # write, and the test would pass for the wrong reason forever.
        from app.db.models.receipt_segment import CREATION_METHODS

        assert METHOD_AI in CREATION_METHODS


@pytest.mark.parametrize("table", ["ai_usage_logs"])
def test_the_ai_usage_table_is_never_written_by_this_milestone(table: str) -> None:
    """The third leg of `TRACE-M8-003`, as far as a test without a database can take it.

    Emptiness after a real journey is asserted in `tests/integration/test_m8_definition_of_done.py`,
    which runs the journey. What this can say is that nothing in the application names the table at
    all — so the integration assertion is not resting on a code path that simply was not taken.
    """

    offenders = [
        str(path.relative_to(BACKEND))
        for path in python_sources(BACKEND / "app")
        if table in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], f"{table} is referenced by application code: {offenders}"
