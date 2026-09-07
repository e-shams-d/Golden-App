"""The gold order screens exist, echo their preconditions, and calculate nothing.

M11 Screens slice 5.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered. Slices 1
to 4 followed the same precedent.

`UI-GOLD-001` says the pricing workspace "refuses to submit against a stale pricing version, using
the `If-Match` the API already requires". The second half was **not true when the slice started**:
the API required it and no read supplied it, which is the third time a screen has been asked to
produce a precondition with no source. That is now a contract-wide check of its own,
`test_preconditions_have_a_source.py`, and what this file asserts is the screens' side of it.

The behavioural half — a second accountant pricing the same order is refused — is in
`tests/integration/test_gold_sale_orders.py`.

Covers: UI-GOLD-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPOSITORY_ROOT / "apps" / "admin-web"
TRADER = REPOSITORY_ROOT / "apps" / "trader-pwa"

ADMIN_MODULE = ADMIN / "src" / "gold-orders.ts"
ADMIN_LIST = ADMIN / "app" / "gold-orders" / "page.tsx"
ADMIN_DETAIL = ADMIN / "app" / "gold-orders" / "[orderId]" / "page.tsx"
TRADER_MODULE = TRADER / "src" / "gold-orders.ts"
TRADER_LIST = TRADER / "app" / "gold-orders" / "page.tsx"
TRADER_DETAIL = TRADER / "app" / "gold-orders" / "[orderId]" / "page.tsx"

SCREENS = (ADMIN_MODULE, ADMIN_LIST, ADMIN_DETAIL, TRADER_MODULE, TRADER_LIST, TRADER_DETAIL)

_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """The file with its comments removed.

    Necessary, as three slices have now proved: these modules explain the rules in prose, and a
    substring check reports the explanation as the violation it describes. A check a prose mention
    can trip is one somebody eventually satisfies by deleting the explanation.
    """

    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", SCREENS, ids=lambda path: f"{path.parts[-3]}/{path.name}")
def test_the_gold_surface_exists(path: Path) -> None:
    """Three files per application: a data module, a list and one order."""

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_neither_bundle_names_the_other_audience_s_path() -> None:
    """`UI-ISO-001`, and this is where it earns its keep more than anywhere so far.

    Both audiences call `/gold-sale-orders` under different guards —
    `owned_or_permitted("gold_sale.create_own", "gold_sale.review")` — so a shared module looks
    obviously right. It would also ship `/pricing-versions` into the trader bundle, a path guarded
    by `gold_sale.price`, a grant no trader can hold. The server would refuse; the point is that
    the path should not be there to try.
    """

    trader = "".join(code(path) for path in (TRADER_MODULE, TRADER_LIST, TRADER_DETAIL))
    assert "pricing-versions" not in trader, (
        "the trader bundle names the pricing path, which is guarded by a grant no trader holds"
    )

    admin = "".join(code(path) for path in (ADMIN_MODULE, ADMIN_LIST, ADMIN_DETAIL))
    assert "/submit" not in admin, (
        "the admin bundle names the trader's submit path; handing over an order is the trader's "
        "act and the centre has no route to do it for them"
    )


def test_every_command_echoes_the_server_s_etag() -> None:
    """The claim `UI-GOLD-001` makes, and the one that had no source until this slice.

    Both modules must capture the `ETag` and refuse a read that returned none — without the header
    the only remaining option is `rv-${record_version}`, which is present, well-formed and compares
    a state nobody observed.
    """

    for module in (ADMIN_MODULE, TRADER_MODULE):
        body = code(module)
        assert "response.etag" in body, f"{module.name} never captures the server's ETag"
        assert "no ETag" in body, (
            f"{module.name} does not refuse a read that returned no ETag, so a command could be "
            "sent with no precondition at all"
        )

    for path in SCREENS:
        assert "rv-" not in code(path), (
            f"{path.name} constructs a version string instead of echoing an ETag"
        )


def test_the_pricing_screen_does_not_compute_the_expected_amount() -> None:
    """The server derives it from the weight and the unit price. A second calculation would agree
    today and disagree the first time rounding changed — and the number a trader was quoted would
    then depend on which of the two they happened to read.

    Checked as an absence of arithmetic on the two fields that would produce it.
    """

    body = code(ADMIN_DETAIL)
    for pattern in (
        r"unit_price_irr\s*\*",
        r"unitPrice\w*\s*\*",
        r"\*\s*Number\(.*weight",
        r"gold_weight\s*\*",
    ):
        assert re.search(pattern, body) is None, (
            f"the pricing screen matches {pattern!r} — it is calculating an amount the server owns"
        )
    assert "expected_amount_irr" in body, (
        "the pricing screen never renders the server's expected amount, so it is either "
        "calculating one or showing none"
    )


def test_the_weight_is_never_parsed_to_a_number() -> None:
    """A weight in grams to three decimal places is not safe as a JSON number.

    `gold_weight` is a string in the contract for the reason `MONEY_TIME_CONTRACT` rule 8 gives for
    amounts. Parsing it to render it would reintroduce exactly the rounding the string prevents,
    and the value shown would differ from the value stored in the digit that matters.
    """

    for path in SCREENS:
        body = code(path)
        for pattern in (r"Number\(\s*\w*[Ww]eight", r"parseFloat\(", r"parseInt\(\s*\w*[Ww]eight"):
            assert re.search(pattern, body) is None, (
                f"{path.name} matches {pattern!r} — a weight is a string and stays one"
            )


def test_an_unpriced_order_is_not_rendered_as_zero() -> None:
    """`expected_amount_irr` is `null` until the centre prices the order.

    Zero is a price. Rendering it would tell a trader the centre had quoted them nothing, which is
    a different and much worse claim than "not yet priced" — and the one they would act on.
    """

    for path in (ADMIN_LIST, ADMIN_DETAIL, TRADER_LIST, TRADER_DETAIL):
        body = code(path)
        assert "expected_amount_irr === null" in body, (
            f"{path.name} does not distinguish an unpriced order from a zero-priced one"
        )


def test_both_navigations_reach_the_screens() -> None:
    """A page nothing links to is a page reached only by typing a URL.

    The admin item carries `gold_sale.read` — a *read* permission, which this navigation's own rule
    normally forbids. The exception is recorded beside it: the acting grant `gold_sale.price` is
    held by nobody who cannot also read, so gating on it would hide the list from a manager who may
    legitimately look at orders without setting a price.
    """

    admin_nav = (ADMIN / "src" / "navigation.ts").read_text(encoding="utf-8")
    assert '"/gold-orders"' in admin_nav, "the admin navigation has no gold orders item"
    entry = admin_nav[admin_nav.index('"/gold-orders"') :]
    assert '"gold_sale.read"' in entry[: entry.index("}")], (
        "the admin gold item carries no permission, which would make it the third ungated item "
        "and break the equality slices 1 and 2 settled"
    )

    trader_nav = (TRADER / "src" / "navigation.ts").read_text(encoding="utf-8")
    assert '"/gold-orders"' in trader_nav, "the trader navigation has no gold orders item"


def test_both_routes_are_in_both_sweeps() -> None:
    """`TRACE-SCREENS-001`: the sweep lists what a person can open, in both applications.

    Both, because slice 3 found the sweep-versus-routes comparison had only ever been implemented
    for `admin-web` — a trader screen could ship unswept with every gate green.
    """

    for app in (ADMIN, TRADER):
        swept = (app / "tests" / "a11y" / "shell.spec.ts").read_text(encoding="utf-8")
        assert '"/gold-orders"' in swept, f"{app.name}: the gold list is not swept"
        assert '"/gold-orders/' in swept, f"{app.name}: no concrete gold order route is swept"
