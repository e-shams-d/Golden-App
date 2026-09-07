"""Dispatch and closure exist, and the override is a decision rather than a field.

M11 Screens slice 7.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else.** Slices 1 to 6 followed the same precedent.

Two things are worth stating before the assertions:

**The precondition gate slice 5 built paid rather than caught.** All three commands in this flow
take `If-Match` against the *order*, and `getGoldSaleOrder` has issued that `ETag` since slice 5 —
so for the first time a slice began by being told its preconditions already had a source.

**It could not have found the other missing source**, and slice 7 did. `POST
.../dispatches/{dispatch_id}/acknowledge` is the trader's own route and nothing returned a dispatch
id to a trader: a **path parameter** with nowhere to come from. That gate asks where an `If-Match`
comes from; this is the same shape one level over, and `GET .../dispatches` is what closes it.

A list rather than a `current_dispatch_id` on the order: `gold_dispatches` carries `superseded` and
`cancelled` among its six statuses with no unique constraint per order, so "the current one" is a
concept the backend does not define, and inventing it in a response would promote a screen's guess
to a contract.

Covers: UI-DISPATCH-001.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from app.queues.registry import BUILT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPOSITORY_ROOT / "apps" / "admin-web"
TRADER = REPOSITORY_ROOT / "apps" / "trader-pwa"
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"

ADMIN_MODULE = ADMIN / "src" / "dispatch.ts"
ADMIN_PAGE = ADMIN / "app" / "gold-orders" / "[orderId]" / "page.tsx"
TRADER_MODULE = TRADER / "src" / "dispatch.ts"
TRADER_PAGE = TRADER / "app" / "gold-orders" / "[orderId]" / "page.tsx"

SCREENS = (ADMIN_MODULE, ADMIN_PAGE, TRADER_MODULE, TRADER_PAGE)

_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """The file with its comments removed — the lesson four slices have now taught."""

    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", SCREENS, ids=lambda path: f"{path.parts[-3]}/{path.name}")
def test_the_dispatch_surface_exists(path: Path) -> None:
    """A module per audience; both act on the order page they already have."""

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_the_dispatch_list_is_served_and_published_and_used() -> None:
    """The read slice 7 added, and the gap it closes.

    Without it the acknowledge route names a dispatch id no trader can obtain — a path parameter
    with no source, which is the same defect as a precondition with no source and one level over.

    **The first version of this test read only the committed contract, and the sabotage run showed
    what that costs.** Control 3 deletes the route from the router; the JSON file on disk is
    unchanged, so the test passed over an application that no longer served it — NOT CAUGHT, and
    insensitive by construction rather than wrong. `pnpm openapi:check` would have caught the drift
    in CI, but a gate that depends on another gate to notice its subject is not asserting anything
    itself.

    So the router is asked first. The contract is still checked, because the two answer different
    questions: what is *served* and what is *published*, and a route that is served without being
    published is a route no client can generate against.
    """

    from app.api.v1.gold_sale_orders import router

    served = {
        (method, getattr(route, "path", ""))
        for route in router.routes
        for method in getattr(route, "methods", set())
    }
    # The router reports its own prefix, so the path is the full one rather than the decorator's
    # literal — checked against what `router.routes` actually holds rather than what the source
    # reads like, which is the point of asking the router at all.
    assert ("GET", "/gold-sale-orders/{order_id}/dispatches") in served, (
        "the router does not serve the dispatch list, so the acknowledge route names a dispatch "
        f"id no trader can obtain. Served: {sorted(served)}"
    )

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    published = contract["paths"].get("/api/v1/gold-sale-orders/{order_id}/dispatches")
    assert published is not None and "get" in published, "the dispatch list is not published"
    assert published["get"]["operationId"] == "listGoldDispatches"

    assert "/dispatches`" in code(TRADER_MODULE), "the trader module never reads the list"
    assert "listDispatches(orderId" in code(TRADER_PAGE), "the trader page never reads the list"


def test_no_screen_invents_a_current_dispatch() -> None:
    """"The current dispatch" is a concept this system does not define.

    Six statuses including `superseded` and `cancelled`, and no unique constraint per order. A
    field or a variable named for it would be a guess given a name, and the guess would be wrong
    the first time a dispatch was superseded.
    """

    for path in SCREENS:
        assert "current_dispatch" not in code(path), (
            f"{path.name} names a current dispatch, which the backend does not define"
        )


def test_the_override_is_absent_unless_somebody_wrote_a_reason() -> None:
    """**The one control here that changes what the system allows.**

    Without a reason the server refuses to dispatch against an order that is not fully paid; with
    one the refusal becomes a recorded override — `guard_override_at` and the reason both come
    back. An empty string would be a reason nobody wrote, recorded as though somebody had, so the
    screen must send `null` rather than `""`.
    """

    module = code(ADMIN_MODULE)
    assert "guard_override_reason: input.guardOverrideReason ?? null" in module, (
        "the module does not send null for an absent override reason"
    )

    page = code(ADMIN_PAGE)
    assert "guardOverrideReason: overrideReason.trim() || null" in page, (
        "the screen sends an empty override reason rather than omitting it, which records an "
        "override nobody authorised"
    )


def test_the_screen_shows_the_pair_the_guard_is_about() -> None:
    """Dispatching against an unpaid order is what the override overrides.

    A screen showing the weight without the two amounts would ask somebody to authorise something
    they cannot see — and the override field would be the only clue that a decision was being
    made at all.
    """

    page = code(ADMIN_PAGE)
    assert "dispatch.confirmedTotal" in page and "dispatch.expectedAmount" in page, (
        "the dispatch section does not show what has been paid against what the order costs"
    )


def test_the_three_warehouse_queues_open_the_order_page() -> None:
    """All three carry order ids, so all three go to the same screen.

    That is also why no separate warehouse screen was built: it would be a second page about the
    same row, and these queues would have to choose between them. §20.1 keeps the refusals on the
    server, so one page offering every control is honest rather than permissive.
    """

    for name in ("orders-ready-for-dispatch", "blocked-dispatches", "receipt-confirmation-work"):
        queue = BUILT.get(name)
        assert queue is not None, f"{name} is no longer built"
        assert queue.detail_path == "/gold-orders", (
            f"{name} points at {queue.detail_path!r} rather than the order page"
        )


def test_the_trader_bundle_cannot_dispatch_or_close() -> None:
    """`UI-ISO-001`. Handing gold over and closing the business are the centre's acts.

    `gold_sale.dispatch` is the warehouse operator's and `gold_sale.review` the accountant's; a
    trader holds neither, and the paths should not be in that bundle to try.
    """

    trader = code(TRADER_MODULE) + code(TRADER_PAGE)
    assert "/close" not in trader, "the trader bundle names the closure path"
    assert '"/gold-sale-orders/${orderId}/dispatches"' not in trader.replace(" ", ""), (
        "the trader bundle posts to the dispatch path"
    )
    assert "recordDispatch" not in trader, "the trader bundle imports the dispatch command"


def test_the_acknowledgement_echoes_the_order_version() -> None:
    """§8.2 moves both rows and the order is the aggregate — the route's own note.

    So the trader's acknowledgement echoes the `ETag` from `readOrder`, which is why this slice
    needed no read of its own for the precondition. The gate slice 5 built said so before the
    screen was written.
    """

    page = code(TRADER_PAGE)
    assert "acknowledge(phase.ifMatch)" in page, (
        "the acknowledgement does not echo the order's ETag"
    )
    for path in SCREENS:
        assert "rv-" not in code(path), (
            f"{path.name} constructs a version string instead of echoing an ETag"
        )
