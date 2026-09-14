"""The attempt search's filters, and the four §17.1 names that are not among them.

M0 slice E. `GET /payment-attempts` exists because proposing a matching candidate takes a
`payment_attempt_id` and no read produced a choosable one — the fifth consecutive slice to find a
command published without the read that makes it operable.

**This file exists because a negative control was NOT CAUGHT.** The route's first draft called
`ATTEMPT_LIST_SPEC.require_filterable(name)` before applying each filter, and a control removing
that call changed nothing: every name in the loop is a literal that is in the spec by construction,
so the call could never fail. It was machinery with no caller, wearing the shape of a guard.

The mistake it was aimed at is real, though, and arrives at a different moment: somebody adds a
query parameter to the route and forgets the spec. That is caught here, at test time, rather than
on a request that would have happened in production.

Covers: CI-ATTEMPTSEARCH-001.
"""

from __future__ import annotations

import inspect
from typing import Any, get_args, get_origin

from app.api.v1.payment_attempts import ATTEMPT_LIST_SPEC, AttemptSummary, list_attempts
from app.db.pagination import InvalidListParameterError

# What `apply_pagination` consumes rather than what the caller filters on. Named here so a new
# pagination parameter does not read as an unallowlisted filter.
PAGINATION = frozenset({"sort", "limit", "cursor"})

# What the route takes from the framework rather than from the query string.
INJECTED = frozenset({"actor", "runtime", "response"})

# §17.1 lists nine filters. These are the ones deliberately not built, each recorded against its own
# reason in the route. Restated here rather than imported, which is the point: a later change that
# quietly allowlisted one would agree with an imported constant and disagree with this list.
NOT_BUILT = (
    "beneficiary_iban_snapshot",
    "bank_profile_version_id",
    "trader_id",
    "bank_result_at",
)


def declared_query_parameters() -> set[str]:
    """The route's own parameters, minus what the framework supplies and what pages the result."""

    return {
        name
        for name in inspect.signature(list_attempts).parameters
        if name not in PAGINATION and name not in INJECTED
    }


def test_every_attempt_filter_is_allowlisted() -> None:
    """A query parameter the spec does not know about is a filter nothing governs.

    **The failure this catches is additive and looks harmless**: somebody adds `trader_id` to the
    signature, applies it in the loop, and never touches `ATTEMPT_LIST_SPEC`. The route works. What
    is lost is the record of what this read can be narrowed by — which is what `ListSpec`'s own
    docstring says the allowlist is for, "not to prevent SQL injection" but to keep an unindexed
    column from becoming filterable by accident.
    """

    declared = declared_query_parameters()

    assert declared == set(ATTEMPT_LIST_SPEC.filters), (
        f"the route declares {sorted(declared)} and the spec allowlists "
        f"{sorted(ATTEMPT_LIST_SPEC.filters)}. Every parameter a caller can narrow this read by "
        "belongs in both."
    )


def test_the_filters_not_built_are_genuinely_not_allowlisted() -> None:
    """The other direction, and the one that matters for the IBAN.

    §17.1 lists a filter by IBAN. Accepting one as a query parameter writes a beneficiary's IBAN
    into every access log and proxy on the way, and POL-003 is **open** — so whether this read can
    be searched by IBAN is the owner's decision. An allowlist that quietly contained the name would
    be that decision made by an implementer.
    """

    for name in NOT_BUILT:
        assert name not in ATTEMPT_LIST_SPEC.filters, (
            f"{name!r} is allowlisted as a filter and the route records it as not built. One of "
            "the two is wrong, and for the IBAN the wrong one discloses a beneficiary."
        )
        try:
            ATTEMPT_LIST_SPEC.require_filterable(name)
        except InvalidListParameterError:
            continue
        raise AssertionError(f"the spec accepted {name!r} as a filter")


def test_the_search_response_carries_no_payee_data() -> None:
    """Asserted over the model's fields rather than over one name.

    The detail read carries neither the beneficiary name nor the IBAN, so a *list* that did would
    disclose more than the screen it links to — and a list discloses it for every attempt at once.
    Written as a rule over the field names so a later field carrying payee data fails this too,
    rather than as two `not in` checks that would pass against `payee_name`.
    """

    for name, field in AttemptSummary.model_fields.items():
        assert "iban" not in name and "beneficiary" not in name and "payee" not in name, (
            f"`AttemptSummary.{name}` looks like payee data; POL-003 is open and this response "
            "carries none"
        )
        # And nothing is smuggled in as a nested object either.
        annotation: Any = field.annotation
        nested = get_args(annotation) if get_origin(annotation) else ()
        assert not any(hasattr(arg, "model_fields") for arg in nested), (
            f"`AttemptSummary.{name}` nests a model, so what it discloses is decided elsewhere"
        )
