"""The incoming payment screens exist, and each precondition comes from its own aggregate.

M11 Screens slice 6.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered. Slices 1
to 5 followed the same precedent.

`UI-INCOMING-001` covers the trader's claim and the accountant's review. What slice 6 found while
building it is worth stating first: **slice 5's precondition gate had recorded one of these gaps
wrongly.** It listed both incoming-payment commands as needing the *receipt's* version. Confirming
does; rejecting a match does not — that route passes `incoming_payment_match_id` and edits the
match row. A single read would have closed the recorded gap while leaving the reject screen with
nothing to echo, and the gate would have gone green.

So there are two reads, and the pairing is asserted here rather than assumed.

The behavioural halves are M10's: `tests/integration/test_incoming_payment_matches.py` and
`test_incoming_confirmation.py`.

Covers: UI-INCOMING-001.
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

ADMIN_MODULE = ADMIN / "src" / "incoming-payments.ts"
ADMIN_PAGE = ADMIN / "app" / "incoming-payments" / "[receiptId]" / "page.tsx"
TRADER_MODULE = TRADER / "src" / "incoming-receipts.ts"
TRADER_ORDER_PAGE = TRADER / "app" / "gold-orders" / "[orderId]" / "page.tsx"

SCREENS = (ADMIN_MODULE, ADMIN_PAGE, TRADER_MODULE, TRADER_ORDER_PAGE)

_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """The file with its comments removed — the lesson three slices have now taught."""

    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", SCREENS, ids=lambda path: f"{path.parts[-3]}/{path.name}")
def test_the_incoming_payment_surface_exists(path: Path) -> None:
    """A module and a screen per audience — the trader's claim lives on their order."""

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_both_reads_are_published_and_both_are_used() -> None:
    """The two reads slice 6 added, in the contract and reached by the screen.

    Both halves, because either alone is a half-built thing this project has shipped before: a
    route no screen calls, or a screen calling a route the contract does not publish.
    """

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for path, operation in (
        ("/api/v1/incoming-payment-receipts/{receipt_id}", "getIncomingPaymentReceipt"),
        (
            "/api/v1/incoming-payment-receipts/{receipt_id}/matches/{match_id}",
            "getIncomingPaymentMatch",
        ),
    ):
        published = contract["paths"].get(path)
        assert published is not None and "get" in published, f"{path} is not published"
        assert published["get"]["operationId"] == operation

    module = code(ADMIN_MODULE)
    assert "/incoming-payment-receipts/${receiptId}`" in module, "the receipt read is not called"
    assert "/matches/${matchId}`" in module, "the per-match read is not called"


def test_the_two_preconditions_come_from_their_own_aggregates() -> None:
    """**The correction slice 6 made to slice 5's recorded gap**, asserted so it cannot drift back.

    Confirming takes the receipt's version; rejecting takes the match's. A screen that echoed the
    receipt's version into a reject would send a well-formed precondition for the wrong row — which
    the server would refuse, but only after somebody had made the decision twice.
    """

    module = code(ADMIN_MODULE)

    reject = module[module.index("export async function rejectMatch") :]
    reject_body = reject[: reject.index("\n}")]
    assert "ifMatch," in reject_body, "reject does not send a precondition at all"

    confirm = module[module.index("export async function confirmPayment") :]
    confirm_body = confirm[: confirm.index("\n}")]
    assert "ifMatch," in confirm_body, "confirm does not send a precondition at all"

    page = code(ADMIN_PAGE)
    # The reject handler reads the match for its own version rather than reusing the page's.
    assert "readMatch(receiptId" in page, (
        "the reject handler does not read the match for its own precondition, so it is echoing "
        "the receipt's version into a command that edits the match row"
    )
    # And the confirm uses the receipt's, which the page rendered.
    assert "confirmPayment(receiptId, phase.ifMatch" in page, (
        "the confirm does not echo the receipt version the page rendered"
    )


def test_no_screen_computes_a_precondition() -> None:
    """`rv-` built here would be a precondition the screen invented."""

    for path in SCREENS:
        assert "rv-" not in code(path), (
            f"{path.name} constructs a version string instead of echoing an ETag"
        )
    for module in (ADMIN_MODULE,):
        body = code(module)
        assert "no ETag" in body, (
            f"{module.name} does not refuse a read that returned no ETag, so a command could be "
            "sent with no precondition at all"
        )


def test_the_trader_bundle_holds_none_of_the_centre_s_judgement() -> None:
    """`UI-ISO-001`, and the strongest case for it in the application.

    A trader may claim they paid and may not say which bank row proves it — the catalogue gives
    them neither `incoming_payment.match` nor `incoming_receipt.read`, and the reason is not only
    authorisation: a trader who could propose the proving row would be deciding their own case.
    """

    trader = code(TRADER_MODULE) + code(TRADER_ORDER_PAGE)
    for forbidden in ("/matches", "/confirm", "incoming-payment-receipts/${"):
        assert forbidden not in trader, (
            f"the trader bundle names {forbidden!r}, which belongs to the centre's judgement"
        )
    assert "incoming-payment-receipts" in code(TRADER_MODULE), (
        "the trader module never submits a claim, so the screen has nothing to file"
    )


def test_an_unconfirmed_claim_is_not_rendered_as_zero() -> None:
    """`confirmed_amount_irr` is `null` until somebody agrees. Zero is an agreement.

    On this screen the difference decides whether the accountant still has work to do, which makes
    it worse here than on the order list: a claim showing `0` reads as reviewed and settled at
    nothing.
    """

    assert "confirmed_amount_irr === null" in code(ADMIN_PAGE), (
        "the review screen does not distinguish an unconfirmed claim from one confirmed at zero"
    )


def test_the_review_screen_is_reached_from_the_queue_the_server_names() -> None:
    """The pairing, from the side that can import the registry.

    `apps/admin-web/test/screens-are-reachable.test.ts` reads this same fact as text, because the
    registry is Python and the frontend genuinely does not know which screen opens a queue row —
    that is slice 4's decision. Neither half is trusted alone.

    **`receipt-confirmation-work` is deliberately not pointed here.** It is the warehouse's queue
    over gold *orders* under `gold_sale.dispatch`; sending it to a receipt screen would be the
    wrong screen for the right row, which is the failure `detail_path` exists to prevent.
    """

    queue = BUILT.get("incoming-receipts-requiring-review")
    assert queue is not None, "the incoming receipts queue is no longer built"
    assert queue.detail_path == "/incoming-payments", (
        f"the queue points at {queue.detail_path!r} rather than the review screen"
    )

    other = BUILT.get("receipt-confirmation-work")
    assert other is not None and other.detail_path != "/incoming-payments", (
        "the warehouse's confirmation queue points at the receipt review screen; its rows are "
        "gold orders, not receipts"
    )


def test_the_review_route_is_in_the_accessibility_sweep() -> None:
    """`TRACE-SCREENS-001`: the sweep lists what a person can open."""

    swept = (ADMIN / "tests" / "a11y" / "shell.spec.ts").read_text(encoding="utf-8")
    assert '"/incoming-payments/' in swept, "the review screen is not in the accessibility sweep"
