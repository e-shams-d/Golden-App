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


def assigned_attributes(path: Path) -> set[str]:
    """Every attribute this module assigns to, as `obj.attr = ...` or in a keyword argument.

    Parsed rather than grepped. A grep for `published` matches this file's own docstring and the
    comment in `receipt_segment.py` explaining that M9 owns the state — the seventh and eighth times
    a scan here would have been defeated by the prose written to justify it.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute):
                    names.add(target.attr)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Attribute):
            names.add(node.target.attr)
        elif isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
    return names


class TestNothingCanPublish:
    """`SVC-PRIVACY-002`. §2.5 of the M8 plan: publication is M9's, and M8 adds no way round it."""

    def test_no_route_names_publication(self) -> None:
        # The whole route table, not a sample. `publications` is doc 05 `:1874`'s path segment and
        # `publishable` is the flag a shortcut would invent.
        offenders = [
            (method, path)
            for method, path in served_routes()
            if "publication" in path or "publishable" in path or "publish" in path
        ]

        assert offenders == [], (
            f"M8 serves a publication route: {offenders}. Publication is M9's, and a path that "
            "exists before its privacy precondition can be enforced is a path that can be used "
            "without one."
        )

    def test_no_command_or_route_assigns_a_publication_flag(self) -> None:
        # **Assignment, not mention.** The forbidden thing is *setting* publishability, and the
        # segment status tuple legitimately contains `published` because M9 will use it — slice 1's
        # `recount` already reads it. So this looks for writes.
        forbidden = {"published", "publishable", "is_published", "published_at", "publication_id"}

        offenders: dict[str, list[str]] = {}
        for path in [*python_sources(COMMANDS), *python_sources(API)]:
            written = assigned_attributes(path) & forbidden
            if written:
                offenders[str(path.relative_to(BACKEND))] = sorted(written)

        assert offenders == {}, (
            f"something in M8 writes a publication field: {offenders}. §16.5 requires a privacy "
            "verification before evidence is published; a writer here could publish without one."
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
