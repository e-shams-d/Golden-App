"""What the crop command must not do, asserted over the code rather than over a run.

M8 slice 4. §16.5 at `15_Agent_Implementation_Plan.md:1057` gives three prohibitions:

    Crop creation MUST NOT confirm evidence, mark an attempt paid, or publish to a trader.

**Asserted as import absences.** A behavioural test can only show that a particular run did not
confirm anything, which is also what a test passes when the confirmation is behind a branch nobody
took. The module's import list is different: a crop cannot confirm evidence it has no way to name.
That makes this a test about reachability, which is the only honest reading of a prohibition.

**Why this file has no database.** Every claim here is about the source text or about a pure
function, and giving it a database would make it skip locally where `INTEGRATION_ADMIN_DATABASE_URL`
is unset — turning three prohibitions into three silences.

Covers: SVC-CROP-001, SVC-CROP-002.
"""

from __future__ import annotations

import ast
import inspect
from decimal import Decimal
from pathlib import Path

import pytest
from app.commands import receipt_crop
from app.exports.crop import RENDER_SCALE, RENDER_SCALE_TEXT, Rectangle

MODULE = Path(inspect.getfile(receipt_crop))
SOURCE = MODULE.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def imported_names() -> set[str]:
    """Every name this module imports, and every module it imports from.

    Parsed rather than grepped, because a grep for `evidence_link` matches the sentence in the
    docstring that explains why there is no such import — this file's own prose would defeat it, a
    mistake this repository has now made five times.
    """

    names: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            names.update(alias.name for alias in node.names)
    return names


# The three things §16.5 forbids, and what each would have to reach for.
#
# **Only one of the three can be broken at M8, and saying so is the point.** `PaymentAttempt` is a
# real class in `app/db/models/payment_batch.py` that this module could import today, so "mark an
# attempt paid" is a live prohibition. Evidence confirmation does not exist yet — M9 builds
# `evidence_links` — and trader publication is an empty queue placeholder. Naming them anyway is
# deliberate: the names are what M9 will add, and this is the test that will be standing there when
# it does. `test_which_prohibitions_can_currently_be_broken` records which is which, so nobody reads
# three passing assertions as three enforced rules.
FORBIDDEN = {
    "confirm evidence": (
        "app.commands.evidence_link",
        "app.db.models.evidence_link",
        "EvidenceLink",
        "confirm_evidence",
    ),
    "mark an attempt paid": (
        "app.commands.payment_attempt",
        "app.db.models.payment_batch",
        "PaymentAttempt",
        "PaymentAttemptAllocation",
    ),
    "publish to a trader": (
        "app.commands.publication",
        "app.workers.tasks.notifications",
        "publish_to_trader",
        "notify_trader",
    ),
}

# Which of the above name something that exists in the tree right now. Written down rather than
# computed so that a mechanism arriving in M9 makes this list wrong and this file the thing that
# says so.
BREAKABLE_TODAY = {"mark an attempt paid", "publish to a trader"}


@pytest.mark.parametrize("prohibition", sorted(FORBIDDEN))
def test_the_crop_command_cannot_reach_what_it_must_not_do(prohibition: str) -> None:
    """`SVC-CROP-002`. Three prohibitions, three separate assertions.

    Separate rather than one loop with one assert, because a single test named "the prohibitions
    hold" tells whoever breaks one of them which file to open and not which rule they broke.
    """

    reachable = imported_names() & set(FORBIDDEN[prohibition])

    assert reachable == set(), (
        f"§16.5 forbids the crop command to {prohibition}, and it now imports {sorted(reachable)}. "
        "If this is deliberate, the prohibition has changed and this test should be the thing that "
        "argues about it."
    )


def test_which_prohibitions_can_currently_be_broken() -> None:
    """The control on the test above, and it changed what that test claims.

    A prohibition against importing something that does not exist passes forever and proves
    nothing — the same shape as a negative control anchored on a string the code never had. Run
    against §16.5's three, this said only one and a half of them are live at M8: `PaymentAttempt` is
    importable today, `app.workers.tasks.notifications` exists as an empty placeholder, and evidence
    confirmation is M9's.

    So the answer is written down rather than worked around. When M9 adds `evidence_links`, this
    assertion fails, and the person adding it is told that a prohibition just became enforceable —
    which is the moment to check that the crop command still honours it.
    """

    tree = Path(inspect.getfile(receipt_crop)).parents[1]
    importable = {
        prohibition
        for prohibition, candidates in FORBIDDEN.items()
        if any(
            (tree / Path(candidate.removeprefix("app.").replace(".", "/") + ".py")).exists()
            for candidate in candidates
            if candidate.startswith("app.")
        )
    }

    assert importable == BREAKABLE_TODAY, (
        f"the set of §16.5 prohibitions that name something real has changed: {sorted(importable)} "
        f"versus the recorded {sorted(BREAKABLE_TODAY)}. If a mechanism has just been built, the "
        "prohibition above is now enforceable and worth re-reading rather than assumed."
    )


def test_the_command_module_touches_no_storage_key() -> None:
    """M4's boundary, which the crop path is the newest way to break.

    `render_pending_crop` needs the source bytes, and the tempting way to get them is
    `storage.open(record.storage_key)`. M7 slice 4 wrote exactly that and the boundary gate refused
    it. ADR-003 has not chosen a production storage adapter, so a change of provider must touch
    `app/storage/` and nothing else.
    """

    # **Over the AST, not the text.** The first version of this assertion was `"storage_key" not in
    # SOURCE` and it failed immediately — on the docstring in `_read` that explains why the module
    # does not do this. That is the sixth time in this repository that a source-text scan has been
    # defeated by the prose written to explain it. An attribute access is what the boundary is
    # about, and it is what the AST can name exactly.
    accesses = [
        node.attr
        for node in ast.walk(TREE)
        if isinstance(node, ast.Attribute) and node.attr == "storage_key"
    ]

    assert accesses == [], (
        "the crop command reads a storage key off a record; ask `app/files/` for the bytes instead"
    )


def test_requesting_a_crop_needs_every_piece_of_provenance() -> None:
    """`SVC-CROP-001`, requirement 8, as a shape rather than a run.

    A `RequestCrop` that can be built without a page, an angle or the client's raster is one whose
    row cannot record what produced the crop. Asserted against the dataclass because a required
    field removed later would otherwise only show up as a test that stopped passing something.
    """

    required = {
        name
        for name, spec in receipt_crop.RequestCrop.__dataclass_fields__.items()
        if spec.default is spec.default_factory  # both MISSING == no default
    }

    assert required == {
        "bank_result_bundle_id",
        "bank_result_bundle_file_id",
        "source_file_id",
        "page_number",
        "rectangle",
        "rotation_degrees",
        "client_source_width",
        "client_source_height",
    }


def test_the_render_scale_is_not_a_request_parameter() -> None:
    """Why `SVC-CROP-004` can claim byte equality at all.

    If the caller could choose a scale, two renders of one rectangle would differ whenever the
    second caller chose differently — and the stored provenance would not say which was used. The
    scale is a constant in `app/exports/crop.py` and recorded in the derivation's parameters, so
    changing it is a visible edit rather than a per-request accident.
    """

    assert "render_scale" not in receipt_crop.RequestCrop.__dataclass_fields__
    # Read from `app/exports/crop.py`, which is where it is decided. Asserting it through the
    # command's namespace was a re-export the command stopped needing, and a test that depends on an
    # incidental import fails for a reason that has nothing to do with what it claims.
    assert RENDER_SCALE == 2.0
    # And the spelling the records use is the same number. These two drifting apart would put one
    # scale in the provenance and another in the pixels.
    assert str(RENDER_SCALE) == RENDER_SCALE_TEXT


def test_a_rectangle_is_decimal_all_the_way_down() -> None:
    """No float reaches the rectangle, at the one place a float would be easy to introduce.

    `Decimal("0.105000")` is what the `NUMERIC(10,6)` column holds. `Decimal(0.105)` is
    `0.1050000000000000044408920985006...`, and a crop re-rendered from that describes a marginally
    different region every time — which is the failure `SVC-CROP-004` exists to catch, arriving
    through a type rather than through a bug.
    """

    exact = Rectangle(
        x=Decimal("0.105000"),
        y=Decimal("0.220000"),
        width=Decimal("0.500000"),
        height=Decimal("0.300000"),
    )

    assert str(exact.x) == "0.105000"
    assert str(Decimal(str(0.105))) == "0.105"
    # RUF032 forbids `Decimal(<float>)` precisely because it is the mistake this test is about, so
    # the rule is suppressed on the one line whose subject is the mistake. Writing it any other way
    # would delete the assertion while leaving it green.
    assert Decimal(0.105) != Decimal("0.105"), (  # noqa: RUF032
        "if these were equal the distinction this test guards would not exist"
    )
