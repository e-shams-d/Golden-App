"""The splitting engine, tested where it is pure.

M6 slice 1. No database, no application, no clock: the engine takes the amount, the four
versioned rules and the evaluation instant as arguments, so every boundary can be asked about
directly. That is the point of `SVC-SPLIT-001` — a function that resolved "the current bank
profile" for itself could not be asked what last Tuesday's preview would have been.

Covers: SVC-SPLIT-001, SVC-SPLIT-002, SVC-SPLIT-003, SVC-SPLIT-004.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, time

import pytest
from app.batching import splitting
from app.batching.splitting import (
    AFTER_CUTOFF_LIMIT,
    DEFAULT_LIMIT,
    NOT_SPLIT,
    SplittingRules,
    applicable_limit,
    split,
)

# 16:00 at the bank, in Tehran. Every instant below is expressed in UTC and converted by the
# engine, because that is what the runtime does — a test that passed local times would not
# exercise the conversion the rule depends on.
CUTOFF = time(16, 0)

# Tehran is UTC+03:30 with no daylight saving since 2022, so 16:00 local is 12:30 UTC.
BEFORE = datetime(2026, 8, 20, 12, 29, 59, tzinfo=UTC)
AT = datetime(2026, 8, 20, 12, 30, 0, tzinfo=UTC)
AFTER = datetime(2026, 8, 20, 12, 30, 1, tzinfo=UTC)


def rules(**overrides: object) -> SplittingRules:
    base: dict[str, object] = {
        "default_transfer_limit_irr": 1_000_000_000,
        "after_cutoff_transfer_limit_irr": 400_000_000,
        "cutoff_time": CUTOFF,
        "splitting_enabled": True,
    }
    base.update(overrides)
    return SplittingRules(**base)  # type: ignore[arg-type]


# --- SVC-SPLIT-001: pure, and versioned by argument --------------------------------------


def test_the_engine_takes_no_session_and_no_clock() -> None:
    """`SVC-SPLIT-001`, asserted on the signature rather than described in a comment.

    The rules are versioned (`15_Agent_Implementation_Plan.md:833`), so they arrive as data. A
    parameter named `session`, or a default of `utc_now()`, would make a preview irreproducible
    the moment the profile changed — and this is the assertion that notices either being added.
    """

    parameters = inspect.signature(split).parameters

    assert list(parameters) == ["amount_irr", "rules", "at"]
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters.values())
    source = inspect.getsource(splitting)
    assert "utc_now" not in source, "the engine reads a clock instead of taking the instant"
    assert "Session" not in source, "the engine takes a database session"


def test_the_same_inputs_always_produce_the_same_rows() -> None:
    """Purity, over a range rather than one case."""

    configuration = rules()
    for amount in range(1, 4_000_000_000, 137_000_017):
        first = split(amount, configuration, BEFORE)
        second = split(amount, configuration, BEFORE)
        assert first == second


# --- SVC-SPLIT-002: the sum is exact -----------------------------------------------------


@pytest.mark.parametrize(
    "amount",
    [
        1,
        999_999_999,
        1_000_000_000,
        1_000_000_001,
        2_000_000_000,
        3_000_000_001,
        # Deliberately not divisible by the limit, which is the case a rounded implementation
        # gets wrong and a tidy one hides.
        1_234_567_891,
        7_777_777_777,
    ],
)
def test_the_rows_sum_to_the_amount_exactly(amount: int) -> None:
    """`SVC-SPLIT-002`. `04_Database_Schema.md:171` forbids a tolerance in as many words."""

    rows = split(amount, rules(), BEFORE)

    assert sum(row.amount_irr for row in rows) == amount
    assert [row.row_order for row in rows] == list(range(1, len(rows) + 1))
    assert all(row.amount_irr > 0 for row in rows), "a zero-amount row reached the file"


def test_no_row_exceeds_the_limit_that_produced_it() -> None:
    """The other half of splitting: the sum being right is not enough if a row is too big."""

    limit = 1_000_000_000
    rows = split(2_500_000_001, rules(default_transfer_limit_irr=limit), BEFORE)

    assert len(rows) == 3
    assert [row.amount_irr for row in rows] == [limit, limit, 500_000_001]
    assert all(row.split_reason == DEFAULT_LIMIT for row in rows)


def test_an_amount_at_the_limit_is_one_row() -> None:
    """The boundary. Splitting an amount the bank accepts whole would be work for nothing."""

    rows = split(1_000_000_000, rules(), BEFORE)

    assert len(rows) == 1
    assert rows[0].split_reason == NOT_SPLIT


# --- SVC-SPLIT-003: nullable limits, and the cutoff boundary ------------------------------


def test_a_null_default_limit_means_no_split() -> None:
    """`SVC-SPLIT-003`. The model's comment: null means the bank publishes no limit."""

    rows = split(
        50_000_000_000,
        rules(default_transfer_limit_irr=None, after_cutoff_transfer_limit_irr=None),
        BEFORE,
    )

    assert len(rows) == 1
    assert rows[0].amount_irr == 50_000_000_000
    assert rows[0].split_reason == NOT_SPLIT


def test_the_after_cutoff_limit_applies_strictly_after_the_cutoff() -> None:
    """`SVC-SPLIT-003`, at the second.

    At exactly 16:00 the ordinary limit still holds. A bank publishing "16:00" means transfers
    *after* 16:00 are treated differently, and treating 16:00:00 as late moves the boundary by
    one second in the customer's disfavour — which is the kind of difference nobody notices
    until a transfer is refused.
    """

    configuration = rules()

    assert applicable_limit(configuration, BEFORE) == (1_000_000_000, DEFAULT_LIMIT)
    assert applicable_limit(configuration, AT) == (1_000_000_000, DEFAULT_LIMIT)
    assert applicable_limit(configuration, AFTER) == (400_000_000, AFTER_CUTOFF_LIMIT)


def test_the_cutoff_is_read_in_the_business_timezone() -> None:
    """The conversion the rule depends on, asserted rather than assumed.

    22:00 UTC is 01:30 the next day in Tehran — before the cutoff, on a different date. An
    engine comparing the UTC clock would call it late and split by the smaller limit.
    """

    late_in_utc = datetime(2026, 8, 20, 22, 0, tzinfo=UTC)

    assert applicable_limit(rules(), late_in_utc) == (1_000_000_000, DEFAULT_LIMIT)


def test_a_null_after_cutoff_limit_leaves_the_default_in_force() -> None:
    """The combination both documents are silent about — G-10 in the M6 plan.

    Two readings differ in the direction that matters. Continuing the default produces more,
    smaller transfers; reading the null as "no limit after the cutoff" would send one large
    transfer the bank had said it would refuse an hour earlier. The conservative one is
    implemented, and it is an assumption rather than a citation, which is why it is recorded.
    """

    configuration = rules(after_cutoff_transfer_limit_irr=None)

    assert applicable_limit(configuration, AFTER) == (1_000_000_000, DEFAULT_LIMIT)
    assert len(split(2_500_000_000, configuration, AFTER)) == 3


def test_a_null_cutoff_never_reaches_the_after_cutoff_limit() -> None:
    """A bank with no cutoff has one limit all day, whatever the second limit says."""

    configuration = rules(cutoff_time=None)

    for instant in (BEFORE, AT, AFTER):
        assert applicable_limit(configuration, instant) == (1_000_000_000, DEFAULT_LIMIT)


# --- SVC-SPLIT-004: disabled means disabled ----------------------------------------------


def test_splitting_disabled_yields_one_row_and_reads_no_limit() -> None:
    """`SVC-SPLIT-004`.

    The limits passed here would split the amount into three if they were consulted, so this
    fails on a future version that checks them anyway — rather than agreeing by coincidence
    with a fixture whose limits happened to be null.
    """

    rows = split(
        2_500_000_000,
        rules(
            splitting_enabled=False,
            default_transfer_limit_irr=1_000_000_000,
            after_cutoff_transfer_limit_irr=400_000_000,
        ),
        AFTER,
    )

    assert len(rows) == 1
    assert rows[0].amount_irr == 2_500_000_000
    assert rows[0].split_reason == NOT_SPLIT


# --- Refusals ----------------------------------------------------------------------------


@pytest.mark.parametrize("amount", [0, -1])
def test_a_non_positive_amount_is_refused(amount: int) -> None:
    """The database already refuses it; reaching here means a revision was built by hand.

    Loud rather than an empty tuple, because a request that produced no rows would vanish from
    the file while still holding an allocation — a payment that never happens and that nothing
    reports as missing.
    """

    with pytest.raises(ValueError, match="cannot be split"):
        split(amount, rules(), BEFORE)


def test_a_non_positive_limit_is_refused() -> None:
    """Zero is not "no limit"; the model's comment says so, and it would never terminate."""

    with pytest.raises(ValueError, match="cannot produce any row"):
        split(1_000, rules(default_transfer_limit_irr=0, after_cutoff_transfer_limit_irr=0), AT)
