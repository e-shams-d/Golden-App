"""Splitting one amount into the rows a bank will accept, and nothing else.

`15_Agent_Implementation_Plan.md:833` makes the splitting rules **versioned**, so this module
takes the four rules as data and never reads a row. That is the whole design: a preview an
accountant looked at last Tuesday must be reproducible from the version it named, and a
function that resolved "the current profile" for itself could not promise that.

It takes no session for the same reason it takes no `now()` — the evaluation instant is an
argument. A pure function of `(amount, rules, instant)` can be tested at the cutoff second,
which is the only way to know the boundary is where the document puts it.

**The sum is exact.** `04_Database_Schema.md:171`: "Outgoing-payment allocation has no hidden
tolerance. Exact equality is required unless a future explicitly modeled fee/rounding
component is introduced." So the residual row carries the remainder rather than the rows being
rounded to something tidy, and `SVC-SPLIT-002` is a property test over amounts that do not
divide evenly.

Covers: SVC-SPLIT-001, SVC-SPLIT-002, SVC-SPLIT-003, SVC-SPLIT-004.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from app.core.time import to_business_time

# The `split_reason` vocabulary. Document 05's example at `:1307` gives exactly one value,
# `bank_limit_after_cutoff`; the other two are its symmetry — a row split by the ordinary
# limit, and a row that was never split. Named here so the API and the tests share one
# spelling rather than two string literals that drift.
NOT_SPLIT = "none"
DEFAULT_LIMIT = "bank_limit_default"
AFTER_CUTOFF_LIMIT = "bank_limit_after_cutoff"


@dataclass(frozen=True, slots=True)
class SplittingRules:
    """The four inputs, lifted out of `bank_profile_versions` so the engine takes no session.

    Mirrors `app/db/models/bank.py:185-195`. Both limits are nullable there, and the model's
    own comment says why: "Null means 'this bank publishes no limit', which is different from
    zero — zero would mean every transfer must be split into nothing."

    `cutoff_time` is a `TIME`, not an instant, and the model explains that too: a cutoff is a
    wall-clock rule — "16:00 at the bank" — evaluated in the configured business timezone. An
    instant would bind it to one date and shift it twice a year wherever daylight saving
    applies.
    """

    default_transfer_limit_irr: int | None
    after_cutoff_transfer_limit_irr: int | None
    cutoff_time: time | None
    splitting_enabled: bool


@dataclass(frozen=True, slots=True)
class ProposedRow:
    """One row of the proposed file. `row_order` is 1-based, per document 05's example."""

    row_order: int
    amount_irr: int
    split_reason: str


def applicable_limit(rules: SplittingRules, at: datetime) -> tuple[int | None, str]:
    """Which limit applies at this instant, and the reason a row split by it would carry.

    **The after-cutoff limit applies strictly after the cutoff.** At exactly the cutoff the
    ordinary limit still holds: a bank publishing "16:00" means transfers *after* 16:00 are
    treated differently, and treating 16:00:00.000 itself as late would move the boundary by
    the width of one second in the customer's disfavour.

    **When the bank publishes no separate after-cutoff limit, the ordinary limit continues.**
    Document 05 and document 04 are both silent on this combination, and the two readings
    differ in the direction that matters: continuing the default produces more, smaller
    transfers, and treating the null as "no limit after the cutoff" would send one large
    transfer a bank had told us it would refuse before the cutoff. The conservative reading is
    implemented and recorded as G-10 in `docs/handoff/M6_IMPLEMENTATION_PLAN.md` §4, because it
    is an assumption and not a citation.
    """

    cutoff = rules.cutoff_time
    after = rules.after_cutoff_transfer_limit_irr

    # Both must be present for the late rule to exist at all: a cutoff with no second limit is
    # a boundary with nothing on the other side of it, and a second limit with no cutoff is a
    # limit that never begins. Either alone leaves the ordinary limit in force all day.
    if cutoff is None or after is None:
        return rules.default_transfer_limit_irr, DEFAULT_LIMIT

    # `to_business_time` rather than a `ZoneInfo` built here: `app/core/time.py` already owns
    # the zone, and a second construction of it is a second place to be wrong when ADR-006's
    # business timezone is revisited.
    if to_business_time(at).time() > cutoff:
        return after, AFTER_CUTOFF_LIMIT

    return rules.default_transfer_limit_irr, DEFAULT_LIMIT


def split(amount_irr: int, rules: SplittingRules, at: datetime) -> tuple[ProposedRow, ...]:
    """The rows one request's current revision becomes.

    Always at least one row: a request that produced none would vanish from the file while
    still holding an allocation, which is the shape of a payment that never happens and that
    nothing reports as missing.
    """

    if amount_irr <= 0:
        # The database already refuses this (`payment_request_revisions` CHECKs
        # `amount_irr > 0`), so reaching here means a caller built a revision by hand. Loud,
        # because a zero-amount row in a bank file is a row somebody has to explain.
        raise ValueError(f"an amount of {amount_irr} cannot be split into bank rows")

    if not rules.splitting_enabled:
        # And the limits are not consulted at all. `SVC-SPLIT-004` asserts that by passing
        # limits that would otherwise split, so a future version that reads them anyway fails
        # rather than agreeing by coincidence.
        return (ProposedRow(row_order=1, amount_irr=amount_irr, split_reason=NOT_SPLIT),)

    limit, reason = applicable_limit(rules, at)
    if limit is None or amount_irr <= limit:
        return (ProposedRow(row_order=1, amount_irr=amount_irr, split_reason=NOT_SPLIT),)

    if limit <= 0:
        raise ValueError(f"a transfer limit of {limit} cannot produce any row")

    rows: list[ProposedRow] = []
    remaining = amount_irr
    while remaining > 0:
        # Integer arithmetic throughout. No division, no float, no rounding: the last row is
        # whatever is left, so the sum is exact by construction rather than by correction.
        taken = limit if remaining > limit else remaining
        rows.append(
            ProposedRow(row_order=len(rows) + 1, amount_irr=taken, split_reason=reason)
        )
        remaining -= taken

    return tuple(rows)
