"""The queue screens exist, hold no copy of the registry, and name every queue in Persian.

M11 Screens slice 2.

**This file exists because the traceability scanner reads `tests/` at the repository root and
nothing else**, so an obligation discharged only by a vitest suite would look uncovered.
`tests/backend/test_approval_screens_exist.py` set the precedent in M7 and states the reasoning at
length; `test_notification_screens_exist.py` followed it in slice 1.

What a Python test can honestly check from here is what the *backend* knows: the sixteen queues in
`BUILT`, the paging parameters the published contract declares, and whether the frontend has
started keeping its own copy of any of it. The behaviour — loading, filtering, following a cursor —
is in `tests/integration/test_queue_index.py` and `apps/admin-web/test/`.

**The label check is the one worth having.** The set of queues lives in the backend and only the
words live in `packages/localization`, which is the right split and also a drift risk in exactly
one direction: a queue added to the registry with no label renders its URL segment. That is a
silent defect — the screen works, it just says `blocked-dispatches` to a Persian reader — and a
missing thing is silent in a way a wrong thing is not.

Covers: UI-QUEUE-001.
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
MESSAGES = REPOSITORY_ROOT / "packages" / "localization" / "src" / "messages.ts"

QUEUE_PAGE = ADMIN / "app" / "queues" / "[queue]" / "page.tsx"
QUEUE_TABLE = ADMIN / "components" / "queue-table.tsx"
QUEUE_INDEX_PANEL = ADMIN / "components" / "queue-index.tsx"
DATA_MODULE = ADMIN / "src" / "queues.ts"
DASHBOARD = ADMIN / "app" / "page.tsx"
SWEEP = ADMIN / "tests" / "a11y" / "shell.spec.ts"
BELLS = (
    ADMIN / "components" / "notification-bell.tsx",
    REPOSITORY_ROOT / "apps" / "trader-pwa" / "components" / "notification-bell.tsx",
)

# Parameter names that would mean offset paging. §19.3 asks for a cursor, and the difference is not
# stylistic: an offset re-reads from the top, so rows shift under somebody draining a queue and
# items are skipped or seen twice — in the one place whose purpose is to touch every row once.
OFFSET_PARAMETERS = frozenset({"offset", "page", "skip", "start"})


@pytest.mark.parametrize(
    "path",
    [QUEUE_PAGE, QUEUE_TABLE, QUEUE_INDEX_PANEL, DATA_MODULE],
    ids=lambda path: path.name,
)
def test_the_queue_surface_exists(path: Path) -> None:
    """Four files: the page, the table every queue shares, the landing panel, the data module."""

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_one_dynamic_page_serves_every_queue() -> None:
    """Sixteen queues and **one** screen, which is what the unified row shape bought.

    Asserted as an absence: no `app/queues/<name>/page.tsx` for any built queue. Sixteen bespoke
    pages would each be a fresh opportunity to add a column nobody authorised, which is the risk
    §19 `:1298`'s last rule exists to bound.
    """

    bespoke = [
        name for name in BUILT if (ADMIN / "app" / "queues" / name / "page.tsx").is_file()
    ]
    assert bespoke == [], (
        f"these queues have their own page: {bespoke}. Every queue returns the same five fields, "
        "so one dynamic route serves all of them; a per-queue page is where an unauthorised "
        "column gets added."
    )


def test_every_built_queue_has_a_persian_label() -> None:
    """**The drift guard.** The queues are the backend's; only the words are the frontend's.

    A queue in `BUILT` with no `queue.<name>` message renders its URL segment — the screen works
    and reads `blocked-dispatches` to a Persian reader. `queueLabel`'s fallback is deliberate and
    is a safety net, not the plan: this test is what makes it rare.
    """

    messages = MESSAGES.read_text(encoding="utf-8")
    unlabelled = [name for name in BUILT if f'"queue.{name}"' not in messages]

    assert unlabelled == [], (
        f"these queues have no Persian label: {unlabelled}. Add a `queue.<name>` entry to "
        "`packages/localization/src/messages.ts`; without one the screen shows the URL segment."
    )


def test_no_label_names_a_queue_that_is_gone() -> None:
    """Guard the guard, the other way. A stale label is a name nothing will ever render.

    Not merely tidiness: the check above passes when a label exists, so an unused label makes the
    message file a second, silently wrong list of what queues there are — which is the drift this
    whole arrangement was designed to avoid.
    """

    labelled = set(re.findall(r'"queue\.([a-z0-9-]+)"', MESSAGES.read_text(encoding="utf-8")))
    stale = sorted(labelled - set(BUILT))

    assert stale == [], (
        f"these labels name no built queue: {stale}. Either the queue was renamed or it never "
        "existed; a label for neither is a claim about a screen nobody can open."
    )


def test_the_frontend_holds_no_copy_of_the_queue_list() -> None:
    """The point of the index route, asserted where it would be undone.

    A screen that hardcoded the sixteen names would drift from the registry, and its failure mode
    is a link to a queue the server no longer serves. The names live in the backend and reach the
    screen through `GET /api/v1/queues`.

    **The label file is deliberately excluded** — it holds every name by design, which is what the
    two tests above are about. What must not hold them is the code that decides *which queues to
    show*, because that decision is the server's.
    """

    for path in (DATA_MODULE, QUEUE_PAGE, QUEUE_TABLE, QUEUE_INDEX_PANEL, DASHBOARD):
        source = path.read_text(encoding="utf-8")
        # Two or more literal queue names in one file is a list; one is a comment naming an
        # example, which the sweep note and several docstrings legitimately do.
        named = sorted(name for name in BUILT if f'"{name}"' in source)
        assert len(named) < 2, (
            f"{path.relative_to(REPOSITORY_ROOT)} names {named} — that is a copy of the "
            "registry. Which queues a person may open is `GET /api/v1/queues`'s answer, and a "
            "second list here drifts the day a queue is renamed."
        )


def test_no_queue_route_declares_an_offset_parameter() -> None:
    """§19.3's paging rule, read from the published contract rather than from the source.

    The integration test proves an offset *does nothing* when sent. This proves no client is
    invited to try: the contract is what a consumer generates from, and a declared `offset` would
    be an invitation regardless of what the handler does with it.
    """

    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    offenders: list[str] = []
    checked = 0

    for path, operations in contract["paths"].items():
        if not path.startswith("/api/v1/queues/"):
            continue
        for method, operation in operations.items():
            if method != "get":
                continue
            checked += 1
            declared = {parameter["name"] for parameter in operation.get("parameters", [])}
            if declared & OFFSET_PARAMETERS:
                offenders.append(f"{path}: {sorted(declared & OFFSET_PARAMETERS)}")
            assert "cursor" in declared, f"{path} declares no cursor, so it cannot be paged"

    # The floor. A path prefix that stopped matching would find no queue routes and report no
    # offenders, which is the failure mode that makes this whole test quiet.
    assert checked == len(BUILT), (
        f"{checked} queue routes were found in the contract against {len(BUILT)} built queues; "
        "the prefix no longer matches and this check is about nothing"
    )
    assert offenders == [], f"these queue routes declare offset paging: {offenders}"


def test_the_queue_route_is_in_the_accessibility_sweep() -> None:
    """`TRACE-SCREENS-001`: the sweep lists what a person can open.

    A concrete queue name rather than the dynamic segment, because the sweep drives a real browser.
    """

    assert '"/queues/' in SWEEP.read_text(encoding="utf-8"), (
        "no queue route is in the admin accessibility sweep"
    )


@pytest.mark.parametrize("path", BELLS, ids=lambda path: path.parts[-3])
def test_each_application_has_its_own_notification_bell(path: Path) -> None:
    """Slice 1 recorded the bell as owed and guessed it needed `ApplicationShell`. It did not.

    `headerContext` was already a slot on the shared shell, so the bell is app-side — which is
    also what `UI-ISO-001` requires: each bell imports its own application's `notifications.ts`,
    and a shared bell would import one of them and undo the split in the component that renders on
    every page.
    """

    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"
    source = path.read_text(encoding="utf-8")
    assert "../src/notifications" in source, (
        f"{path.relative_to(REPOSITORY_ROOT)} does not read this application's own notifications "
        "module; a shared one would put the other audience's path in this bundle"
    )
    # The count is the server's field, not a length. A bell counting unread items in a page is
    # wrong as soon as the list is longer than one page.
    assert "unread_count" in source, (
        f"{path.relative_to(REPOSITORY_ROOT)} does not read `unread_count`; a derived count "
        "disagrees with the server the moment the list is paginated"
    )
