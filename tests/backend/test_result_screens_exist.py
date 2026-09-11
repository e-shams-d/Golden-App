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

    A publish that asked for a step-up would be a control the backend does not have, and the cost
    is not merely cosmetic: a person taught to reauthenticate whenever a screen asks will do it
    for a screen that should not have asked.

    **The claim is "exactly one command carries it", not "no command does."** This test asserted
    the second until M0 slice A2, and the two were indistinguishable only because the one command
    that *does* require a step-up had no screen. Its own message said so at the time —
    "`command_catalog.yaml` requires one for the publication *correction* and not for the
    publish". So the assertion is now counted rather than absolute: the token reaches the
    transport once, from `correctPublication`, and a second occurrence means some other command
    grew one.
    """

    for path in SCREENS:
        source = code(path)
        if path is not DATA_MODULE:
            # The pages themselves never touch the header. The correction dialog collects a
            # password and hands it to the data module; a page building the header itself would be
            # a second place for the binding to be got wrong.
            assert "X-Recent-Auth" not in source and "recentAuthToken" not in source, (
                f"{path.name} sends a step-up header. Only `payment-results.ts` does, and only "
                "for the correction."
            )
            continue

        assert source.count("recentAuthToken") == 1, (
            f"the data module passes a recent-auth token {source.count('recentAuthToken')} times. "
            "`command_catalog.yaml` requires one for `payment_publication.correct_paid_result` "
            "and for no other command on this surface; a second is a screen inventing a control."
        )
        # And it is the correction that carries it. Counting alone would pass if the token moved
        # from the correction to the publish, which is precisely the drift this test exists for.
        correction = source[source.index("export async function correctPublication") :]
        assert "recentAuthToken" in correction, (
            "the recent-auth token is passed by something other than `correctPublication`"
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


def test_the_correction_screen_exists_and_asks_the_second_human_for_a_password() -> None:
    """**A deferral that expired twice, and this is what replaced it.**

    Slice 4 wrote the first version to fail the day a role held `payment_publication.correct`. The
    owner assigned it on 2026-09-08 and it fired. The second version failed the day the route
    declared `X-Recent-Auth`, which the owner's decision of 2026-09-09 made possible. Both fired
    exactly as designed, which is the argument for recording a deferral as an assertion rather
    than as a comment: neither reason could quietly stop being true.

    What replaces them asserts the three things that had to arrive, because a screen that reaches
    the route is not the claim — a screen that reaches it *correctly* is:

    - **the catalogue still asks for the step-up.** If this stops being
      `required_for_approving_second_human`, the dialog below is asking for a password nothing
      requires, and that is worth failing over rather than leaving in place;
    - **the route declares the header**, so the screen is not sending one the server ignores;
    - **the screen asks the approver for their own credentials**, which is the whole of the
      owner's decision. A dialog that took only a reason and a segment would satisfy the first two
      and prove the preparer alone can correct a published result.

    The read chain is asserted separately in `test_the_correction_screen_resolves_its_evidence`,
    because "can reach the command" and "can show a person what they are changing" fail for
    different reasons and a single test would report the wrong one.
    """

    catalogue = json.loads(COMMANDS.read_text(encoding="utf-8"))
    commands = {command["id"]: command for command in catalogue["commands"]}
    correction = commands.get("payment_publication.correct_paid_result")
    assert correction is not None, "the correction command is no longer in the catalogue"
    assert correction.get("recent_auth") == "required_for_approving_second_human", (
        "the catalogue no longer requires a step-up for the correction. The dialog asks a second "
        "human for their password on the strength of this line; revisit the screen rather than "
        "relaxing the assertion."
    )

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    route = contract["paths"]["/api/v1/payment-requests/{request_id}/publications/corrections"]
    headers = {
        parameter["name"].lower()
        for parameter in route["post"].get("parameters", [])
        if parameter.get("in") == "header"
    }
    assert "x-recent-auth" in headers, (
        "the correction route no longer declares X-Recent-Auth, so the screen is sending a header "
        f"the server does not read. Declared headers: {sorted(headers)}"
    )

    reached = [path for path in SCREENS if "/publications/corrections" in code(path)]
    assert len(reached) == 1, (
        f"{len(reached)} screens reach the correction route; expected exactly the publication "
        f"screen's data module: {[path.name for path in reached]}"
    )

    dialog = (ADMIN / "components" / "correction-dialog.tsx").read_text(encoding="utf-8")
    for marker, why in (
        ("correction-approver-username", "the approver is not identified"),
        ("correction-approver-password", "the second human never proves they are present"),
        ("correction.approverHint", "nothing tells the preparer whose password this is"),
        ("correction-confirm", "§13.5's explicit confirmation is missing"),
    ):
        assert marker in dialog, f"the correction dialog has no {marker}: {why}"


def test_the_correction_screen_resolves_its_evidence() -> None:
    """The blocker found behind the step-up, and the reason it was the larger one.

    A publication carries `primary_evidence_link_id`. Until M0 slice A2 the evidence surface was
    three POSTs, `GET /bank-result-bundles/{id}` returned three segment *counts* and no segments,
    and `GET /queues/unresolved-bundles-segments` returns bundles despite its name. So a screen
    holding that id could not show which crop is published, could not offer an alternative, and
    could not name a replacement — and a correction form with a free-text segment id would have
    been a way to publish the wrong evidence twice.

    Asserted over the contract *and* the screen, because either half alone is a shape this
    repository has shipped before: a route no screen calls, or a screen calling a route the
    contract does not publish.
    """

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    for path in (
        "/api/v1/evidence-links/{link_id}",
        "/api/v1/bank-result-bundles/{bundle_id}/receipt-segments",
    ):
        assert "get" in contract["paths"].get(path, {}), (
            f"{path} is not published, so the correction screen cannot resolve what it is changing"
        )

    module = code(DATA_MODULE)
    for marker, why in (
        ("/evidence-links/", "the screen cannot resolve the link a publication cites"),
        ("/receipt-segments", "the screen cannot offer an alternative crop"),
    ):
        assert marker in module, f"the data module never reaches {marker}: {why}"


def test_the_publication_screen_no_longer_explains_an_absence() -> None:
    """The panel is gone because the thing it apologised for arrived.

    `publication.correctionBlocked` existed so that a blank space would not read as software that
    cannot fix a wrong published result. That was the right thing to ship twice and its text was
    false by the end: it told a person the permission had been given to no role, three weeks after
    the owner gave it to two.

    **Asserted rather than deleted, and the direction is what matters.** A test that merely
    stopped checking would leave a screen free to acquire both — a working control *and* a panel
    saying there is none, which is worse than either. The message keys are asserted absent from
    the page, and `test_the_correction_screen_exists_and_asks_the_second_human_for_a_password`
    asserts what stands in their place.

    The strings stay in `messages.ts` for the moment, unreferenced. Removing a key is a separate
    act with its own gate, and a slice that both replaced a control and pruned the vocabulary
    would be two changes reviewed as one.
    """

    source = PUBLICATION_PAGE.read_text(encoding="utf-8")
    for key in ("publication.correctionBlocked", "publication.correctionBlockedTitle"):
        assert key not in source, (
            f"the publication screen still renders {key}. The correction control exists now, so "
            "the panel explaining its absence contradicts the button beside it."
        )
    assert "correction.open" in source, (
        "the publication screen offers no way into the correction, so removing the panel that "
        "explained its absence has left a blank space — which is what that panel existed to avoid"
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
        # deliberately absent from *this* destination**: that queue is the warehouse's, over gold
        # *orders* under `gold_sale.dispatch`, and pointing it here would be the wrong screen for
        # the right row.
        "incoming-receipts-requiring-review": "/incoming-payments",
        # M11 Screens slice 7. All three warehouse queues carry order ids, so all three open the
        # order page — which is where the dispatch controls went, and the reason a separate
        # warehouse screen was not built: it would be a second page about the same row and these
        # queues would have to choose between them.
        "orders-ready-for-dispatch": "/gold-orders",
        "blocked-dispatches": "/gold-orders",
        "receipt-confirmation-work": "/gold-orders",
        # M11 Screens slice 9. The review task screen, closing the gap slice 8's own gate made
        # visible: this queue had been on the dashboard since slice 2 with `detail_path` `None`,
        # so an accountant could see work waiting and could not open it.
        "reconciliation-tasks": "/review-tasks",
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

    # `extracted_amount_irr` is excluded, and the exclusion is narrow on purpose. It is what a
    # person *read off a bank receipt*, carried on the segment type M0 slice A2 added so the
    # correction screen can label the crops it offers. It is a read field on a read type and no
    # command body has one; matching it here would have made this test fail for a reason it is not
    # about, and raising the count to 3 would have made it stop noticing the thing it is about.
    module = DATA_MODULE.read_text(encoding="utf-8").replace("extracted_amount_irr:", "")
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
