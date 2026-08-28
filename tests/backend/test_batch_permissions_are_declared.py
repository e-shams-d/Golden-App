"""Each batch route declares its own grant, and none of them declares a request permission.

M6 slice 2. Both obligations here are about **declarations**, not behaviour, and that is the
whole point — slice 1's ninth negative control proved a behavioural test cannot tell them apart.
Swapping `payment_batch.read` for `payment_batch.create` on the preview changed nothing that any
integration test could see, because the RBAC seed grants `accountant` both grants and the
permission negative signs in as a role holding neither.

So the assertions are equality over the declared set, read through the same closure walk M5's
Definition-of-Done gate uses. A route declaring *both* grants would pass a membership check while
still requiring the mutation grant, which is the failure being prevented.

`TRACE-BATCH-001` — no batch route declares a `payment_request.*` permission — is not tidiness.
M5's gate classifies a route as request-scoped partly by the permissions it declares, so a batch
route declaring one would pull itself into that gate's scope and silently change what the
milestone's prohibition is asserted over. The prohibition would still pass, over a different set.

No database, so neither can become a skip.

**This file replaces `tests/backend/test_batch_preview_declares_a_read.py`**, which slice 1 wrote
for the preview alone. Keeping both would put one rule in two places: the seed assertion at the
bottom was identical in each, and a future change to the read/create split would have to find
both files to stay honest. The preview is now one row in `EXPECTED`, and slice 1's reasoning is
the second and third paragraphs above.

Covers: SEC-BATCH-002, TRACE-BATCH-001, SEC-BATCH-001.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from test_permission_guards import declared_permissions, routes_of

CREATE = ("POST", "/api/v1/payment-batches")
LIST = ("GET", "/api/v1/payment-batches")
DETAIL = ("GET", "/api/v1/payment-batches/{batch_id}")
PREVIEW = ("POST", "/api/v1/payment-batches/preview")
FINALIZE = ("POST", "/api/v1/payment-batches/{batch_id}/versions/{version_id}/finalize")
REPLACE = ("POST", "/api/v1/payment-batches/{batch_id}/versions")
CANCEL = ("POST", "/api/v1/payment-batches/{batch_id}/cancel")
APPROVAL_VIEW = (
    "GET",
    "/api/v1/payment-batches/{batch_id}/versions/{version_id}/approval-view",
)
APPROVE = ("POST", "/api/v1/payment-batches/{batch_id}/versions/{version_id}/approve")
REJECT = ("POST", "/api/v1/payment-batches/{batch_id}/versions/{version_id}/reject")
PREVIEW_EXPORT = (
    "POST",
    "/api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/preview",
)
FINAL_EXPORT = (
    "POST",
    "/api/v1/payment-batches/{batch_id}/versions/{version_id}/exports/final",
)

# What each route must declare, and nothing else. The create is the only one that writes.
EXPECTED: dict[tuple[str, str], set[str]] = {
    CREATE: {"payment_batch.create"},
    LIST: {"payment_batch.read"},
    DETAIL: {"payment_batch.read"},
    PREVIEW: {"payment_batch.read"},
    # M6 slice 3, and its own grant is the whole point: the actor recorded by this
    # command is the one M7 must refuse as an approver, so conflating finalize with
    # any other batch permission would blur the identity
    # `FINANCIAL_INTEGRITY_BASELINE.md` §5 compares.
    FINALIZE: {"payment_batch_version.finalize"},
    # M6 slice 4. Each its own grant, and the version-level one is separate from the
    # container's for the reason `FINANCIAL_INTEGRITY_BASELINE.md` §5 gives: the
    # version-level actors are the ones a manager's approval is checked against.
    REPLACE: {"payment_batch_version.create"},
    # **The one route that declares two, and the equality above is what keeps that honest.**
    # G-5: the owner's 2026-08-25 decision under DOC-CONFLICT-056 split cancellation authority
    # by the batch's *state* — `cancel_draft` before a manager has decided, `cancel_approved`
    # after. A route dependency runs before the batch is loaded and so cannot choose between
    # them; `either_cancellation_permission` admits a caller holding either and
    # `commands.authority_for_cancelling` refuses on the status.
    #
    # Declaring only one would break a role outright rather than tighten anything: only
    # `cancel_draft` locks the manager out of the route entirely, only `cancel_approved` stops
    # an accountant cancelling their own draft. `required_permissions` is what the
    # manager-only prohibition reads, and it sees neither of these as required — which is the
    # distinction between an alternative and a requirement.
    CANCEL: {"payment_batch.cancel_draft", "payment_batch.cancel_approved"},
    # M7 slice 1. Three separate grants for three different authorities, and the
    # separation is the milestone's whole subject.
    #
    # `read_approval_view` goes to `accountant`, `manager` and `read_only_auditor`
    # (`permission_catalog.yaml:475`) — an auditor must be able to see what was decided
    # without being able to decide, and the accountant who prepared the file must be
    # able to check their own work, which they can do here and, by SEC-APPROVAL-002,
    # cannot do by approving.
    APPROVAL_VIEW: {"payment_batch_version.read_approval_view"},
    # Approve and reject are separate rows in the catalogue (`:480`, `:483`) and stay
    # separate here. Collapsing them into one "decide" grant would mean anybody who may
    # stop a payment may also authorise one.
    APPROVE: {"payment_batch_version.approve"},
    REJECT: {"payment_batch_version.reject"},
    # M7 slice 2. `permission_catalog.yaml:490` gives this to `accountant` and not to `manager`,
    # which is the right way round and worth stating: rendering a file to look at is preparation
    # work, and giving the manager who approves it the ability to produce it too would put both
    # sides of the export on one desk.
    PREVIEW_EXPORT: {"bank_export.generate_preview"},
    # M7 slice 3. A separate grant from the preview's (`permission_catalog.yaml:492`), and the
    # separation is real: a preview authorises nothing, a final export is the file that goes to a
    # bank. Collapsing them would mean anybody who may look at a rendering may also produce the
    # one that gets sent.
    FINAL_EXPORT: {"bank_export.generate_final"},
}

SEED = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "backend"
    / "alembic"
    / "versions"
    / "20260801_0008_seed_rbac_catalogue.py"
)


def _declared(app_factory: Any) -> dict[tuple[str, str], set[str]]:
    app, _runtime, _settings = app_factory()
    return {(method, path): declared_permissions(route) for method, path, route in routes_of(app)}


def test_each_batch_route_declares_exactly_the_grant_its_effect_needs(
    app_factory: Any,
) -> None:
    """Equality, not membership, for the reason the module docstring gives."""

    declared = _declared(app_factory)

    for route, expected in sorted(EXPECTED.items()):
        assert route in declared, (
            f"{route} is not in the route table, so it is either unmounted or the reader has "
            "stopped seeing it — and this file would then assert nothing about it"
        )
        assert declared[route] == expected, (
            f"{route[0]} {route[1]} declares {sorted(declared[route])} and must declare "
            f"{sorted(expected)}. A read that requires the create grant makes the only role "
            "able to look at a proposed batch the role able to make one."
        )


def test_no_batch_route_declares_a_payment_request_permission(app_factory: Any) -> None:
    """`TRACE-BATCH-001`.

    Checked over every route whose path starts with the batch prefix, rather than over the four
    named above: a fifth batch route added without an entry in `EXPECTED` would escape the test
    above, and this one is what catches it in the meantime.
    """

    declared = _declared(app_factory)
    offenders = {
        route: sorted(grant for grant in grants if grant.startswith("payment_request."))
        for route, grants in declared.items()
        if route[1].startswith("/api/v1/payment-batches")
    }
    offenders = {route: grants for route, grants in offenders.items() if grants}

    assert offenders == {}, (
        "a batch route declares a request-scoped permission, which pulls it into the scope of "
        f"M5's route classification gate and changes what that gate asserts over: {offenders}"
    )


def test_every_batch_route_is_covered_by_the_expectation_above(app_factory: Any) -> None:
    """A new batch route cannot arrive unnoticed.

    Without this, slice 3's finalize route would ship with no declared-permission assertion and
    the two tests above would still pass — over the four routes they happen to name. The failure
    message says what to do, because the answer is always "add the row", never "delete the test".
    """

    declared = _declared(app_factory)
    batch_routes = {
        route for route in declared if route[1].startswith("/api/v1/payment-batches")
    }

    assert batch_routes == set(EXPECTED), (
        "the batch routes and this file's expectations have diverged.\n"
        f"  unexpected routes: {sorted(batch_routes - set(EXPECTED))}\n"
        f"  expected but gone: {sorted(set(EXPECTED) - batch_routes)}\n"
        "Add each new route to EXPECTED with the single grant its effect needs."
    )


def test_the_two_batch_grants_are_held_by_different_role_sets() -> None:
    """Why equality above is worth having, read from the seed rather than assumed.

    If every role holding `payment_batch.read` also held `.create`, the distinction would be
    theoretical and the equality assertions would be ceremony. `business_admin` holds the read
    and not the create, so choosing the wrong grant hides every batch from a real role — and if
    a future seed change made the two sets identical, this fails and asks whether the
    assertions above still earn their place.
    """

    seed = SEED.read_text(encoding="utf-8")

    def holders(code: str) -> set[str]:
        return set(re.findall(rf'\("([a-z_]+)", "{re.escape(code)}"\)', seed))

    readers = holders("payment_batch.read")
    creators = holders("payment_batch.create")

    assert readers, "no role holds payment_batch.read, so every batch route is unreachable"
    assert creators, "no role holds payment_batch.create, so no batch can be made"
    assert readers - creators, (
        "every role that may read a batch may also create one, so the read/create distinction "
        f"protects nobody. readers={sorted(readers)} creators={sorted(creators)}"
    )
