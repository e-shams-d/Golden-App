"""The trader's result screen exists, offers from the server, and invents no taxonomy.

M11 Screens slice 3.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered.
`test_approval_screens_exist.py` set the precedent in M7; slices 1 and 2 followed it.

`UI-PUB-001` has two halves and the server side of the first is **already proven**:
`tests/integration/test_trader_publications.py::test_another_trader_gets_404_and_not_403` has held
since M9. What slice 3 adds is the screen, and the claims worth checking from here are the two
ways it could quietly disagree with the backend:

- deciding for itself which buttons to show, instead of reading `allowed_actions`;
- inventing the closed list of dispute reasons that `app/commands/trader_result.py` **deliberately
  refused to write**.

The second is the one that nearly shipped. The first draft of the screen offered four invented
`reason_code` values, and the command module's own docstring argues against exactly that: "A closed
list invented here would refuse a trader whose complaint does not fit one of the options somebody
guessed — and this is the only surface in the system whose user is a customer rather than staff, so
the cost of that is a phone call instead of a record."

Covers: UI-PUB-001.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.commands.trader_result import ACKNOWLEDGE_OPERATION, DISPUTE_OPERATION

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TRADER = REPOSITORY_ROOT / "apps" / "trader-pwa"

PAGE = TRADER / "app" / "requests" / "[requestId]" / "result" / "page.tsx"
DATA_MODULE = TRADER / "src" / "publications.ts"
DETAIL_PAGE = TRADER / "app" / "requests" / "[requestId]" / "page.tsx"
SWEEP = TRADER / "tests" / "a11y" / "shell.spec.ts"
SWEEP_GATE = TRADER / "test" / "screens-are-swept.test.ts"

# The one value document 05 documents. Anything else in the screen's reason list is a category
# somebody invented, which is the thing the command module refused to do.
DOCUMENTED_REASON = "beneficiary_did_not_receive"

# A reason code is a lowercase identifier in a quoted string next to `code:`. Narrow on purpose:
# a looser pattern would match the message keys beside them and report the labels as codes.
REASON_CODE = re.compile(r'code:\s*"([a-z_]+)"')


def test_the_result_screen_exists() -> None:
    """The screen no trader has had since M9 published the first result."""

    assert PAGE.is_file(), f"{PAGE.relative_to(REPOSITORY_ROOT)} is missing"
    assert DATA_MODULE.is_file(), f"{DATA_MODULE.relative_to(REPOSITORY_ROOT)} is missing"


def test_the_buttons_are_read_from_allowed_actions() -> None:
    """`UI-PUB-001`: absent rather than disabled, and decided by the server.

    Both command ids are imported from the module that owns them rather than spelled here, so a
    rename breaks this test instead of leaving it matching a string nothing uses.
    """

    source = PAGE.read_text(encoding="utf-8")
    assert "allowed_actions" in source, (
        "the result screen does not read `allowed_actions`, so it is deciding for itself which "
        "commands are legal — the second list beside the commands' guards that the projection "
        "exists to prevent"
    )
    for command in (ACKNOWLEDGE_OPERATION, DISPUTE_OPERATION):
        assert command in source, f"the screen never names {command}"


def test_the_screen_offers_no_invented_dispute_reasons() -> None:
    """**The check worth having**, because the first draft of this screen failed it.

    `app/commands/trader_result.py` left `reason_code` un-enumerated on purpose, and a dropdown is
    exactly how that decision gets undone: the server accepts anything, so whatever list the
    screen shows becomes the closed list M9 refused to write — for the one audience in this system
    that is a customer rather than a colleague.

    Two codes are allowed here: the value document 05 documents, and `other`, which is a general
    escape rather than a guessed category. A third means somebody has started building a taxonomy
    on the screen, and it should be built in the catalogue instead.
    """

    codes = set(REASON_CODE.findall(PAGE.read_text(encoding="utf-8")))
    assert codes, "no reason codes were found; the pattern no longer matches the screen"

    invented = sorted(codes - {DOCUMENTED_REASON, "other"})
    assert invented == [], (
        f"the result screen offers dispute reasons nobody approved: {invented}. `reason_code` is "
        "deliberately not enumerated in the backend — see `app/commands/trader_result.py` — and a "
        "list on the screen is the same closed list arriving through a different door. The set "
        "belongs in the catalogue, which the M9 plan already records as owed."
    )


def test_the_complaint_itself_is_free_text() -> None:
    """The other half of the same decision: the person's own words must have somewhere to go.

    A required description is what makes a two-item reason list acceptable rather than limiting.
    Without it, `other` would be a category with no content.
    """

    source = PAGE.read_text(encoding="utf-8")
    assert "<textarea" in source, "there is nowhere for a trader to say what is actually wrong"
    assert "required" in source, "the description is optional, so `other` can carry no meaning"


def test_the_precondition_is_the_servers_etag_and_is_not_refreshed() -> None:
    """**The screen must not re-read before acting, and that is the opposite of its sibling.**

    `app/requests/[requestId]/page.tsx` re-reads immediately before every command — "the `If-Match`
    is one request old, never one page old" — and that is right for its commands, where a trader is
    editing their own draft and a 412 would be noise.

    Here it would defeat the guard. `command_catalog.yaml`'s
    `current_publication_identity_revalidated` exists so that **a correction landing while the
    trader is reading is refused**: publishing N+1 moves the request, so the version the person was
    looking at is no longer current. A fresh read before sending makes the precondition always
    current, and the trader silently agrees to a result they never saw.

    Asserted structurally because the positive version needs two concurrent actors and a database;
    `test_a_stale_if_match_refuses_a_trader_response` is the server-side half and has held since
    M9.
    """

    source = PAGE.read_text(encoding="utf-8")
    assert "phase.ifMatch" in source, (
        "the screen does not send the `ETag` from the read it rendered, so its precondition is "
        "not the version the person was looking at"
    )
    assert "readRequest(requestId)" not in source.replace("readRequest(requestId, signal)", ""), (
        "the screen re-reads the request outside its loader, which makes the precondition always "
        "current and defeats `current_publication_identity_revalidated`"
    )
    # And no arithmetic. `rv-${...}` built here would be a precondition the screen invented.
    assert "rv-" not in source, "the screen constructs a version string instead of echoing an ETag"


def test_the_screen_is_reachable_from_the_request_it_belongs_to() -> None:
    """A page nothing links to is a page reached only by typing a URL.

    Linked from `allowed_actions` like every other control on the detail page, rather than from a
    status string — the same source of truth, so the link cannot appear when the screen has
    nothing to offer.
    """

    source = DETAIL_PAGE.read_text(encoding="utf-8")
    assert "/result" in source, "no link from the request to its published result"
    assert ACKNOWLEDGE_OPERATION in source, (
        "the link is not conditioned on `allowed_actions`, so it is guessing from something else"
    )


def test_the_route_is_swept_and_the_sweep_is_now_compared_against_the_routes() -> None:
    """`TRACE-SCREENS-001`, and slice 3's second finding.

    The obligation's sweep-versus-routes comparison was implemented for `admin-web` only, so a
    trader screen could ship unswept with every gate green. Porting it found `/login`, `/evidence`
    and `/offline` unswept — the trader login among them, which is the screen every trader must use
    before any other. The obligation's own history records it catching `admin-web`'s `/login`
    unswept since M3; this app's was never checked.
    """

    assert SWEEP_GATE.is_file(), (
        "the trader application has no sweep-versus-routes gate, so `TRACE-SCREENS-001` is "
        "enforced for one of the two applications"
    )
    swept = SWEEP.read_text(encoding="utf-8")
    assert "/result" in swept, "the result screen is not in the accessibility sweep"
    for route in ('"/login"', '"/evidence"', '"/offline"'):
        assert route in swept, f"{route} is a trader screen the sweep never opens"


@pytest.mark.parametrize("path", [PAGE, DATA_MODULE], ids=lambda path: path.name)
def test_the_screen_claims_no_version_history(path: Path) -> None:
    """§20.3 gives a trader their **active** publication and nothing else.

    There is no trader-facing history route, so a screen offering one would be offering a list it
    cannot fetch. The plan asked for "its version history" and this is the deviation: what the
    trader gets is `publication_version`, and a version above 1 is said in words.

    Checked as an absence of the centre's history **path**, because that is the specific mistake —
    a screen reaching for `/payment-requests/{id}/publications` would be reading the internal
    history, which §20.3 reserves for staff.

    The first version of this check looked for the bare word `/publications` and failed on the
    module's own import, `from "../../src/publications"`. **A substring was the wrong question:**
    the defect is an API path, so the pattern is the path's shape.
    """

    reaching = re.search(r"payment-requests/[^\"'`\n]*/publications", path.read_text("utf-8"))
    assert reaching is None, (
        f"{path.name} reaches for {reaching.group(0) if reaching else ''} — the centre's "
        "publication history, which §20.3 reserves for internal users"
    )
