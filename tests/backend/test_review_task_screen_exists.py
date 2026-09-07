"""The review task screen exists, and the queue that shows its rows opens them.

M11 Screens slice 9 — the gap slice 8's own gate made visible, closed in the slice after.

`reconciliation-tasks` has been built, permission-aware and on the dashboard since slice 2, and
its `detail_path` was `None`: an accountant could see that work was waiting and could not open it.
**A queue that reports work nobody can reach is worse than a missing one**, because the count is a
promise. Nothing failed, no request errored, and it was true for eleven milestones — the only
reason anybody noticed is that a gate asked which operations a person can reach.

That is the argument for slice 8 in one sentence, and this file is what it bought.

Covers: TRACE-SCREENS-002.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.queues.registry import BUILT

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ADMIN = REPOSITORY_ROOT / "apps" / "admin-web"

MODULE = ADMIN / "src" / "review-tasks.ts"
PAGE = ADMIN / "app" / "review-tasks" / "[taskId]" / "page.tsx"

_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_LINE = re.compile(r"^\s*//.*$", re.M)


def code(path: Path) -> str:
    """The file with its comments removed — the lesson five slices have now taught."""

    return _LINE.sub("", _BLOCK.sub("", path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("path", (MODULE, PAGE), ids=lambda path: path.name)
def test_the_review_task_surface_exists(path: Path) -> None:
    assert path.is_file(), f"{path.relative_to(REPOSITORY_ROOT)} is missing"


def test_the_queue_opens_the_screen() -> None:
    """The gap, closed — and asserted from the registry rather than from the page.

    `detail_path` is the server's answer to which screen opens a row, so this is where the claim
    belongs. The frontend half is `apps/admin-web/test/screens-are-reachable.test.ts`, which counts
    a published destination as a link.
    """

    queue = BUILT.get("reconciliation-tasks")
    assert queue is not None, "the reconciliation queue is no longer built"
    assert queue.detail_path == "/review-tasks", (
        f"the queue points at {queue.detail_path!r}; its rows are review tasks and a screen for "
        "them now exists, so leaving it `None` would report work nobody can reach"
    )


def test_the_resolution_codes_come_from_the_row() -> None:
    """**The vocabulary is the server's**, and M8 published it on the row for exactly this.

    A list written in the screen is the copy that drifts, and the drift is not cosmetic: a code the
    command refuses is a 400 in front of somebody finishing a piece of work, and one it accepts but
    nobody expected is a row nothing can group afterwards. Grouping is what a queue is for.

    This is the opposite of slice 3's dispute reason, and the difference is real: there no
    catalogue names a set and the audience is a customer, so a closed list would turn a complaint
    away. Here the catalogue names one and the audience is staff.
    """

    page = code(PAGE)
    assert "phase.task.accepted_resolution_codes.map" in page, (
        "the screen does not render the server's resolution vocabulary"
    )
    # And no list of its own **where the options are rendered**. The first version of this check
    # banned any two-string array and matched `OPEN`, the status set the screen legitimately holds:
    # a status is a fact about the workflow this screen reads, where a resolution code is a value
    # the *command* validates. Only the second belongs to the server, so only the second is
    # forbidden — and the check now looks at the option loop rather than at the file.
    options = page[page.index("chooseResolution") :]
    options = options[: options.index("</select>")]
    assert not re.search(r'\[\s*"[a-z_]+"', options), (
        "the resolution options are rendered from a list written in the screen rather than from "
        "the row's `accepted_resolution_codes`"
    )


def test_every_command_echoes_the_read_s_etag() -> None:
    """`GET /manual-review-tasks/{task_id}` had no ETag until slice 5's contract-wide gate.

    This is the first screen to use the one it gained, so computing a version here would waste that
    and reintroduce the defect — a precondition present, well-formed, and about a state nobody
    observed. A shared queue is where it matters most: two people opening the same item is the
    normal case.
    """

    for path in (MODULE, PAGE):
        assert "rv-" not in code(path), (
            f"{path.name} constructs a version string instead of echoing an ETag"
        )
    module = code(MODULE)
    assert "no ETag" in module, (
        "the module does not refuse a read that returned no ETag, so a command could be sent with "
        "no precondition at all"
    )
    # Each of the four commands takes the precondition rather than finding one.
    for command in ("assignTask", "startTask", "resolveTask", "cancelTask"):
        section = module.split(f"export async function {command}", 1)
        assert len(section) == 2, f"{command} is missing from the module"
        assert "ifMatch" in section[1][:600], f"{command} does not send a precondition"


def test_the_screen_does_not_resolve_the_subject() -> None:
    """§13.1 gives `entity_type` and `entity_id` for navigation and nothing else.

    No read here joins through them, and a screen that resolved them would be a second way into a
    row — with its own guard to get wrong. `SVC-TASK-002` asserts the same over the query surface.
    """

    page = code(PAGE)
    assert "entity_id" in page, "the screen does not name the subject at all"
    assert "entity_type" in page
    # Naming is rendering. Fetching would mean a request built from those fields.
    assert not re.search(r"(fetch|request)\([^)]*entity_", page), (
        "the screen builds a request from the subject fields, which is a second way into a row"
    )
