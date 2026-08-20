"""The preview declares the read grant, and only that. `SEC-BATCH-001`'s other half.

M6 slice 1, and written because a negative control did not fire. The integration suite already
proves that *some* permission is required: an internal caller with no role is refused, and so
is a trader. Then the sabotage `payment_batch.read` → `payment_batch.create` was applied and
**nothing failed**, because the RBAC seed grants `accountant` both (`:245`, `:246`) — so the
route could have demanded the mutation grant and every behavioural test would still have
passed.

That is the difference between "a permission is required" and "*this* permission is required",
and only the second is what the obligation claims: a route that writes nothing must not require
the grant that authorises writing, or the only role able to look at a proposed batch becomes the
role able to make one. `business_admin` holds `payment_batch.read` and not `.create` (`:276`),
so the difference is not hypothetical — it decides whether they can see a preview.

Asserted on the declaration rather than through a caller, using the same closure walk M5's
Definition-of-Done gate uses. No database, so it cannot become a skip.

Covers: SEC-BATCH-001.
"""

from __future__ import annotations

from typing import Any

from test_permission_guards import declared_permissions, routes_of

PREVIEW = ("POST", "/api/v1/payment-batches/preview")


def test_the_preview_declares_exactly_the_read_permission(app_factory: Any) -> None:
    """One permission, and it is the read.

    Equality rather than membership: a route that declared both would pass a membership check
    while still requiring the mutation grant, which is the failure this test exists for.
    """

    app, _runtime, _settings = app_factory()
    declared = {
        (method, path): declared_permissions(route) for method, path, route in routes_of(app)
    }

    assert PREVIEW in declared, (
        f"{PREVIEW} is not in the route table, so either it is unmounted or the reader has "
        "stopped seeing it — and this whole file would then assert nothing"
    )
    assert declared[PREVIEW] == {"payment_batch.read"}, declared[PREVIEW]


def test_the_two_batch_grants_are_held_by_different_role_sets() -> None:
    """Why the assertion above is worth having, read from the seed rather than assumed.

    If every role holding `payment_batch.read` also held `.create`, the distinction would be
    theoretical and this file would be ceremony. `business_admin` holds the read and not the
    create, so choosing the wrong one hides the preview from a real role — and if a future seed
    change made the two sets identical, this fails and asks whether the assertion above still
    earns its place.
    """

    from pathlib import Path

    seed = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "backend"
        / "alembic"
        / "versions"
        / "20260801_0008_seed_rbac_catalogue.py"
    ).read_text(encoding="utf-8")

    import re

    def holders(code: str) -> set[str]:
        return set(re.findall(rf'\("([a-z_]+)", "{re.escape(code)}"\)', seed))

    readers = holders("payment_batch.read")
    creators = holders("payment_batch.create")

    assert readers, "no role holds payment_batch.read, so the preview is unreachable"
    assert creators, "no role holds payment_batch.create"
    assert readers - creators, (
        "every role that may read a batch may also create one, so the read/create distinction "
        "no longer protects anybody — reconsider whether the preview's guard still matters"
    )
