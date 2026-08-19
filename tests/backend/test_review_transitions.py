"""The transitions slice 7 implements, compared against document 06 itself.

M5 slice 7. `SVC-REVIEW-001` and `SVC-REVIEW-003` both say "enumerated from the state
machine rather than listed", and this is that enumeration. Needs no database: it compares
a parsed document against two module-level tables, so it runs in milliseconds and belongs
here rather than beside the integration tests that drive the routes.

Parsed rather than transcribed, for the reason `test_payment_request_schema.py` gives at
length: a transcription can be wrong in the same direction as the code. It earned that
here twice before a route existed.

- The plan's first draft listed the review transitions as
  `submitted_to_center → under_accountant_review → needs_trader_correction |
  eligible_for_batching`, which drops the arrow document 06 draws at `:586` straight from
  `submitted_to_center` to `needs_trader_correction`. An accountant who can see at a
  glance that an IBAN is wrong would have had to open a review before handing it back.
- `create_revision` moved a request to `submitted_to_center` unconditionally, so editing a
  draft filed it. The arrows into `submitted_to_center` are parsed here too, which is what
  makes that a failing test rather than a behaviour nobody wrote down.

Covers: SVC-REVIEW-001, SVC-REVIEW-003.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.commands.payment_request import (
    CANCELLABLE,
    CORRECTABLE,
    ELIGIBLE,
    NEEDS_CORRECTION,
    REVIEW_TRANSITIONS,
    SUBMITTED,
    UNDER_REVIEW,
)
from app.db.models.payment_request import M5_REACHABLE_STATUSES

WORKFLOWS = (
    Path(__file__).resolve().parents[2]
    / "Implementation Docs"
    / "02_Architecture_and_Contracts"
    / "06_Workflows_and_State_Machines.md"
)

# `    submitted_to_center --> under_accountant_review: start review`
ARROW = re.compile(r"^\s*([a-z_]+)\s*-->\s*([a-z_]+)\s*:\s*(.+?)\s*$")

# `| `draft` | Trader may cancel |`
CANCEL_ROW = re.compile(r"^\|\s*`([a-z_]+)`[^|]*\|\s*(.+?)\s*\|\s*$")


def _section(heading: str, until: str) -> list[str]:
    """The lines between two headings.

    Both headings are matched exactly. Document 06 reuses status names across six state
    machines — `cancelled` appears in seven separate code blocks — so a parse that read the
    whole file would mix the payment request's arrows with the batch's and the attempt's,
    and would pass while proving something about a different workflow.
    """

    lines = WORKFLOWS.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if line.strip() == heading)
    end = next(
        index for index, line in enumerate(lines[start + 1 :], start + 1) if line.strip() == until
    )
    return lines[start:end]


def documented_origins() -> dict[str, set[str]]:
    """Which states each state is reachable from, per §13.2's diagram."""

    origins: dict[str, set[str]] = {}
    for line in _section("## 13.2 Request state machine", "## 13.3 Revision lifecycle"):
        match = ARROW.match(line)
        if match is None:
            continue
        source, destination, _label = match.groups()
        origins.setdefault(destination, set()).add(source)
    return origins


def documented_cancellation() -> dict[str, tuple[bool, bool]]:
    """§29.1's table as `state -> (a trader may, a reason is required)`.

    Read from the prose rather than from a mapping written here: the cell either mentions
    the trader or it does not, and it either mentions a reason or it does not. Deriving the
    two flags any other way would be the transcription this file exists to avoid.
    """

    rules: dict[str, tuple[bool, bool]] = {}
    for line in _section("## 29.1 Payment request", "## 29.2 Batch/version/export"):
        match = CANCEL_ROW.match(line)
        if match is None:
            continue
        state, permission = match.groups()
        lowered = permission.lower()
        rules[state] = ("trader" in lowered, "reason" in lowered)
    return rules


def test_the_parse_finds_a_state_machine_at_all() -> None:
    """Guard the guard. Every assertion below is vacuous against an empty parse."""

    origins = documented_origins()

    assert len(origins) >= 10, f"only {len(origins)} destinations parsed from §13.2"
    assert documented_cancellation().keys() >= {"draft", "submitted_to_center", "batched"}


def test_the_review_transitions_are_exactly_the_documented_ones() -> None:
    """`SVC-REVIEW-001`. Both directions: nothing missing, and nothing invented."""

    origins = documented_origins()
    implemented = {
        transition.destination: set(transition.origins) for transition in REVIEW_TRANSITIONS
    }

    for destination in (UNDER_REVIEW, NEEDS_CORRECTION, ELIGIBLE):
        assert destination in implemented, f"no command reaches {destination}"
        assert implemented[destination] == origins[destination], (
            f"the code reaches {destination} from {sorted(implemented[destination])} and "
            f"document 06 draws it from {sorted(origins[destination])}"
        )


def test_submission_accepts_exactly_the_documented_origins() -> None:
    """The arrows into `submitted_to_center`, which is where slice 5's defect lived.

    `create_revision` set the status to `submitted_to_center` for any correctable request,
    so a trader editing a draft filed it and `submit` — which then accepted only `draft` —
    could never be called on it afterwards. Document 06 draws two arrows in, `:584` from
    `draft` and `:588` from `needs_trader_correction`, and both are the submit command.
    """

    assert set(CORRECTABLE) == documented_origins()[SUBMITTED]


def test_no_review_transition_reaches_a_state_m5_does_not_implement() -> None:
    """A transition into a state no command can leave is a dead end that looks alive."""

    for transition in REVIEW_TRANSITIONS:
        assert transition.destination in M5_REACHABLE_STATUSES
        for origin in transition.origins:
            assert origin in M5_REACHABLE_STATUSES


def test_cancellation_is_permitted_from_exactly_the_documented_states() -> None:
    """`SVC-REVIEW-003`, restricted to the states M5 reaches.

    §29.1 also covers `batched` and `sent_to_bank` and later, and M6 owns both. The
    restriction is asserted rather than assumed: a state M5 can reach and §29.1 permits,
    but this table omits, would be silently uncancellable.
    """

    documented = documented_cancellation()
    reachable = {state for state in documented if state in M5_REACHABLE_STATUSES}

    assert set(CANCELLABLE) == reachable, (
        f"the code permits cancellation from {sorted(CANCELLABLE)} and §29.1 permits it "
        f"from {sorted(reachable)} among the states M5 reaches"
    )


def test_the_cancellation_actor_and_reason_rules_match_the_document() -> None:
    """`SVC-REVIEW-003`. The `under_accountant_review` row is the one that matters.

    It reads "Internal with reason" where its neighbours read "Trader/internal", so the
    exclusion is deliberate: a trader may not pull a request out from under the accountant
    reading it.
    """

    documented = documented_cancellation()

    for state, rule in CANCELLABLE.items():
        trader_may, reason_required = documented[state]
        assert rule.trader_may == trader_may, (
            f"§29.1 says of {state}: {'a trader may' if trader_may else 'internal only'}"
        )
        assert rule.reason_required == reason_required, (
            f"§29.1 {'requires' if reason_required else 'does not require'} a reason "
            f"for {state}"
        )
