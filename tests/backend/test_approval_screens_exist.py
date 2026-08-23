"""The approval screens exist, are gated, and are in the sweep that checks them.

Screens slice 1. **The field-by-field parse is not here** — it is in
`apps/admin-web/test/approval-screens.test.ts`, which reads §13.2 and §13.3 out of the
specification and asserts a label for every entry, exactly as
`tests/backend/test_approval_read_shape.py` does for the API. `pnpm check` runs it, and
`verify-native.sh` runs `pnpm check`.

This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else, so an obligation discharged only by a vitest suite would look uncovered. Rather
than move the parse somewhere it does not belong, this asserts the three structural facts a
Python test can honestly check — the screens are there, the sweep opens them, and the menu is
gated on the right grant — and says where the rest lives. `UI-NAV-001` set the precedent:
`tests/integration/test_navigation_is_not_a_control.py` is its root-level half.

Covers: UI-APPROVAL-001, UI-APPROVAL-002, UI-APPROVAL-003, UI-APPROVAL-004.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPOSITORY_ROOT / "apps" / "admin-web"

QUEUE_PAGE = ADMIN / "app" / "batches" / "page.tsx"
DETAIL_PAGE = (
    ADMIN / "app" / "batches" / "[batchId]" / "versions" / "[versionId]" / "page.tsx"
)
CLIENT = ADMIN / "src" / "batches.ts"
NAVIGATION = ADMIN / "src" / "navigation.ts"
A11Y_SPEC = ADMIN / "tests" / "a11y" / "shell.spec.ts"
FIELD_TEST = ADMIN / "test" / "approval-screens.test.ts"

QUEUE_PATH = '"/batches"'
DETAIL_PATH = '"/batches/00000000-0000-4000-8000-000000000000/versions/'


@pytest.mark.parametrize(
    "page", [QUEUE_PAGE, DETAIL_PAGE, CLIENT, FIELD_TEST], ids=lambda path: path.name
)
def test_the_screen_and_its_client_exist(page: Path) -> None:
    """The screens are files, not a plan.

    Trivial, and it is the assertion that would have failed for two milestones: the money path's
    backend was complete and none of these files existed. A milestone can be entirely green with
    no way to reach it.
    """

    assert page.exists(), f"{page.relative_to(REPOSITORY_ROOT)} does not exist"


@pytest.mark.parametrize("marker", [QUEUE_PATH, DETAIL_PATH], ids=["queue", "detail"])
def test_both_screens_are_in_the_accessibility_sweep(marker: str) -> None:
    """`UI-APPROVAL-004`. The sweep keeps a fixed list so a new page is a visible edit.

    The list is fixed rather than derived from the route table on purpose — its own comment says
    why, and M5 proved it: `pnpm check` went green over a screen the sweep had never opened. So a
    page added without a line here is a page nobody checks, and this is the line.
    """

    assert marker in A11Y_SPEC.read_text(encoding="utf-8"), (
        f"{marker} is not in the admin a11y sweep's path list"
    )


def test_the_queue_is_gated_on_the_approval_view_permission() -> None:
    """`UI-APPROVAL-003`, structurally. The behavioural half is the vitest suite's.

    `payment_batch_version.read_approval_view` and not `payment_batch.read`: the first is what the
    route itself is guarded on, and gating the menu on the second would put the item in front of
    somebody whose every click ends in a 403.

    And not `.approve`, which goes to `manager` alone — that would hide the screen from the
    auditor who must see what was decided and the accountant who must check their own work.
    """

    navigation = NAVIGATION.read_text(encoding="utf-8")

    assert '"/batches"' in navigation, "the approval queue has no navigation entry"
    assert '"payment_batch_version.read_approval_view"' in navigation
    assert '"payment_batch_version.approve"' not in navigation, (
        "the menu is gated on the approve grant, which hides the screen from two of the three "
        "roles that hold read_approval_view"
    )


def test_the_screen_does_not_decide_the_separation_rule_for_itself() -> None:
    """`UI-APPROVAL-001`'s riskiest field, asserted where a Python test can see it.

    The separation-of-duty status arrives decided, per actor, from the API. A screen that compared
    the signed-in administrator against the version's finalizer would be a second opinion about a
    rule the database enforces — and the two would eventually disagree, on the screen of somebody
    about to authorise a payment.
    """

    detail = DETAIL_PAGE.read_text(encoding="utf-8")

    assert "view.separation_of_duty" in detail
    for forbidden in ("actor_id", "currentUser", "signedInAs"):
        assert forbidden not in detail, (
            f"the detail screen reads {forbidden!r}, which suggests it is deciding the "
            "separation rule rather than rendering the server's answer"
        )


def test_the_field_parse_is_where_this_file_says_it_is() -> None:
    """The pointer, asserted rather than left as prose.

    This file's whole justification is that the real check lives elsewhere. If that suite were
    renamed or its parse removed, the justification would be false and these four obligations
    would be covered by three structural assertions — which is not what they say.
    """

    parse = FIELD_TEST.read_text(encoding="utf-8")

    assert "21_UI_Design_System_and_Screen_Specification.md" in parse, (
        "the vitest suite no longer reads the specification, so nothing parses the field lists"
    )
    assert "13.2 Approval queue" in parse
    assert "13.3 Approval detail" in parse
