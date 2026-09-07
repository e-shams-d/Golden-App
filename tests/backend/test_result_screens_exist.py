"""The centre's result screens exist, invent no control, and say why one is missing.

M11 Screens slice 4.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered.
`test_approval_screens_exist.py` set the precedent in M7; slices 1 to 3 followed it.

`UI-RESULT-001`'s wording was corrected by this slice, and the two corrections are what most of
this file asserts:

- **the step-up belongs to the correction, not to the publish.** The obligation first asked for the
  recent-auth dialog on the publish button. §8.11 describes the dialog *component* and says nothing
  about which commands need one; `command_catalog.yaml` gives
  `payment_publication.correct_paid_result` `recent_auth: "required_for_approving_second_human"`
  and gives `payment_publication.publish` no such field at all. A screen sending `X-Recent-Auth`
  where the server does not ask for it is a screen inventing a control — and asking somebody to
  reauthenticate on request is how a habit of typing passwords into dialogs is built.
- **the correction screen is not built**, because `payment_publication.correct` is granted to no
  role pending ADR-SEC-009. Building it would produce a surface nobody can open, which is the
  defect M3 hit five times. The obligation's original clause — "cannot be reached by a role that
  holds only the preparer half" — is *trivially* true when it cannot be reached by anybody, and an
  assertion that passes for the wrong reason is worse than none.

Covers: UI-RESULT-001.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from app.queues.registry import BUILT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPOSITORY_ROOT / "apps" / "admin-web"
CONTRACT = REPOSITORY_ROOT / "services" / "backend" / "openapi" / "v1.json"
CATALOGUE = REPOSITORY_ROOT / "docs" / "governance" / "permission_catalog.yaml"
COMMANDS = REPOSITORY_ROOT / "docs" / "governance" / "command_catalog.yaml"

ATTEMPT_PAGE = ADMIN / "app" / "payment-attempts" / "[attemptId]" / "page.tsx"
PUBLICATION_PAGE = ADMIN / "app" / "requests" / "[requestId]" / "publication" / "page.tsx"
DATA_MODULE = ADMIN / "src" / "payment-results.ts"
REQUEST_PAGE = ADMIN / "app" / "requests" / "[requestId]" / "page.tsx"
SWEEP = ADMIN / "tests" / "a11y" / "shell.spec.ts"

SCREENS = (ATTEMPT_PAGE, PUBLICATION_PAGE, DATA_MODULE)

# Block comments then line comments, in that order: a `//` inside a block comment is part of the
# block, and stripping lines first would leave the block's opener behind.
_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """The file with its comments removed.

    **Necessary, and this file proved it twice on its first run.** These modules *explain* the
    rules in prose — "never `rv-${record_version}` built here", "`X-Recent-Auth` is enforced on two
    surfaces and neither is here" — and a substring check reported both explanations as the
    violations they describe.

    `apps/admin-web/test/preconditions-come-from-the-server.test.ts` records the same lesson and
    the reason it matters: **a check a prose mention can trip is one somebody eventually satisfies
    by deleting the explanation**, which is the worst possible outcome for a rule whose whole value
    is that the next person understands it. Slice 3's sabotage guard hit this too, which makes it
    three times in two slices.
    """

    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", SCREENS, ids=lambda path: path.name)
def test_the_result_surface_exists(path: Path) -> None:
    """Two screens and one data module, for commands M9 built and nothing ever called."""

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_no_screen_sends_a_step_up_the_server_does_not_require() -> None:
    """The first correction to this obligation, asserted so it cannot drift back.

    `X-Recent-Auth` is enforced on two surfaces in this application — role permission changes and
    batch version approval — and neither is here. A publish that asked for it would be a control
    the backend does not have, and the cost is not merely cosmetic: a person taught to
    reauthenticate whenever a screen asks will do it for a screen that should not have asked.
    """

    for path in SCREENS:
        source = code(path)
        assert "X-Recent-Auth" not in source, (
            f"{path.name} sends a step-up header. `command_catalog.yaml` requires one for the "
            "publication *correction* and not for the publish; a screen adding it is inventing a "
            "control."
        )
        assert "recentAuthToken" not in source, (
            f"{path.name} passes a recent-auth token to the transport for a command that does "
            "not require one"
        )


def test_the_catalogue_still_puts_the_step_up_where_this_slice_says_it_is() -> None:
    """Guard the correction itself. If the catalogue moves, the screens must be revisited.

    Read from `command_catalog.yaml` rather than restated: the whole reason the obligation was
    wrong is that it was written from a screen-specification section which does not decide this.
    """

    catalogue = json.loads(COMMANDS.read_text(encoding="utf-8"))
    commands = {command["id"]: command for command in catalogue["commands"]}

    publish = commands.get("payment_publication.publish")
    assert publish is not None, "the publish command is no longer in the catalogue"
    assert "recent_auth" not in publish, (
        "the catalogue now requires a step-up for publishing. The publish screen must grow the "
        "dialog §8.11 specifies, and this test should be updated deliberately rather than removed."
    )

    correction = commands.get("payment_publication.correct_paid_result")
    assert correction is not None, "the correction command is no longer in the catalogue"
    assert correction.get("recent_auth") == "required_for_approving_second_human", (
        "the correction's step-up requirement changed; the reasoning in the plan and in "
        "`payment-results.ts` was written against this value"
    )


def test_the_correction_screen_is_absent_and_its_grant_is_still_unassigned() -> None:
    """The second correction, and it expires by itself the day the grant is assigned.

    `payment_publication.correct` has `default_roles: []` because POL-002 defers the preparer and
    approver split to ADR-SEC-009. A screen behind it would answer 403 to everybody — the
    `bank_profile.activate_version` shape this project already carries once.

    **Asserted rather than left as a comment**, in the same shape as the notifications exemption
    in `test_navigation_is_not_a_control.py`: the day a role holds the grant, this fails and
    whoever assigned it has to decide whether the screen should now exist.
    """

    catalogue = CATALOGUE.read_text(encoding="utf-8")
    entry = re.search(
        r"^ {6}payment_publication\.correct:\n((?:[ ]{8}.*\n)*)", catalogue, re.M
    )
    assert entry is not None, "payment_publication.correct is no longer in the catalogue"

    roles = re.search(r"default_roles: \[([^\]]*)\]", entry.group(1))
    assert roles is not None, "the correction permission no longer declares default_roles"
    assert roles.group(1).strip() == "", (
        f"payment_publication.correct is now granted to [{roles.group(1)}]. The correction screen "
        "was not built because nobody could open it; that has changed, and slice 4's deferral "
        "should be revisited rather than this assertion relaxed."
    )

    # And no screen reaches for the route in the meantime.
    for path in SCREENS:
        source = path.read_text(encoding="utf-8")
        assert "/corrections" not in source, (
            f"{path.name} reaches the correction route, which no role is permitted to call"
        )


def test_the_publication_screen_explains_the_missing_control() -> None:
    """A blank space would read as software that cannot fix a wrong result. It can.

    The authority to do so has not been assigned, which is a different sentence — and the one the
    screen says. Asserted because the alternative failure is silent: nobody complains about a
    button that was never there.
    """

    source = PUBLICATION_PAGE.read_text(encoding="utf-8")
    assert "publication.correctionBlocked" in source, (
        "the publication screen does not say why there is no correction control, so its absence "
        "reads as a defect"
    )


def test_every_command_echoes_a_precondition_and_computes_none() -> None:
    """`If-Match` comes from the server's `ETag`, never from arithmetic.

    The read this slice added exists for exactly this: before it, no route returned an attempt's
    `record_version` and a screen could only have built `rv-${n}` itself. That value would be
    present, well-formed and meaningless — the worst of the three available states, as
    `apps/admin-web/test/preconditions-come-from-the-server.test.ts` records.
    """

    for path in SCREENS:
        assert "rv-" not in code(path), (
            f"{path.name} constructs a version string instead of echoing an ETag"
        )

    module = code(DATA_MODULE)
    assert "response.etag" in module, "the data module never captures the server's ETag"
    assert "no ETag" in module, (
        "the data module does not refuse a read that returned no ETag, so a command could be "
        "sent with no precondition at all"
    )


def test_the_attempt_read_is_published_and_is_what_the_screen_uses() -> None:
    """The route this slice added, in the contract and reached by the screen.

    Both halves, because either alone is a half-built thing this project has shipped before: a
    route no screen calls, or a screen calling a route the contract does not publish.
    """

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    path = contract["paths"].get("/api/v1/payment-attempts/{attempt_id}")
    assert path is not None and "get" in path, (
        "the attempt read is not in the published contract, so the four commands' precondition "
        "still has no source"
    )
    assert path["get"]["operationId"] == "getPaymentAttempt"

    module = DATA_MODULE.read_text(encoding="utf-8")
    assert "/payment-attempts/${attemptId}" in module, "the data module does not call the read"


def test_the_queue_rows_link_where_the_server_says_and_nowhere_else() -> None:
    """`detail_path` is the server's answer, and the frontend holds no map of its own.

    Sixteen queue names mapped to sixteen destinations in the frontend would drift, and the failure
    mode is the *wrong screen for the right row* — an accountant opening somebody else's work
    believing it was theirs. The two attempt queues carry a destination as of this slice; the rest
    carry `None` and render no link.
    """

    table = (ADMIN / "components" / "queue-table.tsx").read_text(encoding="utf-8")
    assert "listing.detail_path" in table, (
        "the queue table does not read the server's destination, so it is deciding for itself "
        "where a row opens"
    )

    # Each queue with a destination, and where it goes. An equality rather than a floor: a queue
    # pointed at the wrong screen is the failure `detail_path` exists to prevent, and only naming
    # the pairs catches it. Slices add rows here as they build screens.
    expected = {
        # M11 Screens slice 4. The attempt result screen.
        "sent-attempts-awaiting-result": "/payment-attempts",
        "failed-partial-retry-payments": "/payment-attempts",
        # M11 Screens slice 6. The incoming payment review screen. **`receipt-confirmation-work` is
        # deliberately absent**: that queue is the warehouse's, over gold *orders* under
        # `gold_sale.dispatch`, and pointing it here would be the wrong screen for the right row.
        "incoming-receipts-requiring-review": "/incoming-payments",
    }
    linked = {name: queue.detail_path for name, queue in BUILT.items() if queue.detail_path}

    assert linked == expected, (
        f"the queues declaring a destination are {linked}, expected {expected}. A new entry means "
        "a later slice built a screen; a changed one means a queue now points somewhere else, "
        "which is the wrong-screen-for-the-right-row failure this field exists to prevent."
    )


def test_both_screens_are_in_the_accessibility_sweep() -> None:
    """`TRACE-SCREENS-001`: the sweep lists what a person can open."""

    swept = SWEEP.read_text(encoding="utf-8")
    assert '"/payment-attempts/' in swept, "the attempt screen is not in the sweep"
    assert "/publication" in swept, "the publication screen is not in the sweep"


def test_the_publication_screen_is_reachable_from_its_request() -> None:
    """A page nothing links to is a page reached only by typing a URL."""

    assert "/publication" in REQUEST_PAGE.read_text(encoding="utf-8"), (
        "no link from the request to its publication screen"
    )


def test_no_command_body_carries_an_amount_except_the_retry() -> None:
    """§17 `:1131`'s "amount is exact", honoured by absence.

    The confirmations describe a movement the attempt already knows the size of, so a
    client-supplied figure could disagree with the row — and the absence of the field is a stronger
    guarantee than any check on one. The retry is the exception and not an inconsistency: its
    amount is a *decision* about the unresolved remainder rather than a restatement.
    """

    module = DATA_MODULE.read_text(encoding="utf-8")
    # `amount_irr` appears in the retry body and in the attempt type. Two, and no more: a third
    # would mean a confirmation had grown one.
    assert module.count("amount_irr:") == 2, (
        f"`amount_irr:` appears {module.count('amount_irr:')} times in the data module; the "
        "attempt type and the retry body are the only two places it belongs"
    )
    for command in ("confirm-paid", "confirm-failed", "mark-retry-required"):
        section = module.split(command, 1)
        assert len(section) == 2, f"{command} is not called by the data module"
        assert "amount_irr" not in section[1].split("}", 1)[0], (
            f"the {command} body carries an amount, which §17 `:1131` keeps on the attempt"
        )
