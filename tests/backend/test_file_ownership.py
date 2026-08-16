"""Who may reach a file, as a decision function.

Covers: SEC-FILEDL-003.

The route-level consequences are in `tests/integration/test_file_download.py`. This file
is about the registry: that an unregistered category denies, that the deny path is the
fall-through rather than a raise somebody could catch, and that every catalogued purpose
has a resolver written out rather than defaulted.
"""

from __future__ import annotations

import uuid

import pytest
from app.files.ownership import (
    FileFacts,
    categories_without_a_resolver,
    internal_only,
    may_access,
    published_or_uploader,
    resolver_for,
    sensitive_internal_bundle,
    uploader_or_internal,
)
from app.files.purposes import purpose_ids
from app.security.actor import ActorContext, ActorType, Audience

TRADER_ID = uuid.uuid4()
OTHER_TRADER_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()


def staff(*permissions: str) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.ADMIN_USER,
        actor_id=STAFF_ID,
        audience=Audience.ADMIN,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
        roles=frozenset({"accountant"}),
        permissions=frozenset(permissions),
    )


def trader(actor_id: uuid.UUID = TRADER_ID) -> ActorContext:
    return ActorContext(
        actor_type=ActorType.TRADER_USER,
        actor_id=actor_id,
        audience=Audience.TRADER,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
        trader_id=uuid.uuid4(),
    )


def facts(category: str, *, uploader: uuid.UUID | None = TRADER_ID) -> FileFacts:
    return FileFacts(
        category=category,
        visibility_scope="internal_only",
        uploaded_by_actor_type="trader_user",
        uploaded_by_actor_id=uploader,
    )


def test_a_category_with_no_resolver_is_denied_to_everyone() -> None:
    """SEC-FILEDL-003, and the property the whole registry exists for.

    Including a staff actor holding every permission there is. If a permissive default is
    ever added — "internal actors may see anything" is the tempting one — this is the test
    that fails.
    """

    unknown = facts("a_category_no_module_registered")
    assert resolver_for(unknown.category) is None

    everything = staff("file.download", "file.preview", "file.read_sensitive_bundle")
    assert may_access(everything, unknown) is False
    assert may_access(trader(), unknown) is False


def test_the_denial_is_a_return_not_a_raise() -> None:
    """Guard the guard.

    A registry that raised on an unknown category would be equally safe until somebody
    wrapped the call in a `try`. Returning `False` means the deny path is the ordinary
    path and cannot be swallowed.
    """

    assert may_access(staff("file.download"), facts("nothing_registered_this")) is False


def test_every_catalogued_purpose_has_a_resolver() -> None:
    """The other direction: a purpose the catalogue offers and the registry forgot is a
    file nobody can ever read, which looks like a storage fault rather than a missing
    line."""

    assert categories_without_a_resolver() == frozenset()
    for purpose in purpose_ids():
        assert resolver_for(purpose) is not None, purpose


def test_a_trader_cannot_reach_an_internal_only_file() -> None:
    """A statement covers every trader at once, so no trader may read one — even the
    trader who somehow uploaded it."""

    assert internal_only(staff(), facts("bank_statement")) is True
    assert internal_only(trader(), facts("bank_statement", uploader=TRADER_ID)) is False


def test_a_bundle_needs_the_sensitive_grant_as_well_as_staff() -> None:
    """`15_Agent_Implementation_Plan.md:721`. A bundle mixes many traders' results in one
    document, so reading it is a decision about all of them — narrower than
    `internal_only`, not merely staff-only."""

    bundle = facts("bank_result_bundle_source")
    assert sensitive_internal_bundle(trader(), bundle) is False
    assert sensitive_internal_bundle(staff("file.download"), bundle) is False
    assert sensitive_internal_bundle(staff("file.read_sensitive_bundle"), bundle) is True


def test_a_trader_reaches_only_the_file_they_uploaded() -> None:
    """The comparison is against the stored uploader, never against anything the request
    carries. Knowing another trader's file id must not make it readable."""

    mine = facts("payment_request_source", uploader=TRADER_ID)
    theirs = facts("payment_request_source", uploader=OTHER_TRADER_ID)

    assert uploader_or_internal(trader(TRADER_ID), mine) is True
    assert uploader_or_internal(trader(TRADER_ID), theirs) is False
    assert uploader_or_internal(staff(), theirs) is True


def test_a_file_with_no_recorded_uploader_is_not_owned_by_a_trader() -> None:
    """A worker-created derivative has no uploader id. `None == None` must not become
    ownership, which is the shape of bug that a nullable comparison invites."""

    orphan = facts("payment_request_source", uploader=None)
    assert uploader_or_internal(trader(), orphan) is False


def test_publication_grants_nothing_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """SEC-FILEDL-005's unit half.

    M4 builds no publication, so a `trader_visible_after_publication` file is refused to
    every trader but its uploader. Written as a refusal rather than left absent so M9 edits
    an existing check instead of discovering there was never one.
    """

    del monkeypatch
    receipt = facts("incoming_payment_receipt", uploader=OTHER_TRADER_ID)
    assert published_or_uploader(trader(TRADER_ID), receipt) is False
    assert published_or_uploader(trader(OTHER_TRADER_ID), receipt) is True


def test_no_resolver_consults_a_storage_address() -> None:
    """`FileFacts` is what a resolver may know, and it carries no storage triple.

    Passing the ORM row would have worked and would have put `storage_key` one attribute
    access from an ownership decision. The boundary M4's Definition of Done rests on is
    that a storage address stays inside the file service, so the narrow structure makes
    the wider access impossible rather than merely discouraged.
    """

    fields = set(FileFacts.__dataclass_fields__)
    assert fields == {
        "category",
        "visibility_scope",
        "uploaded_by_actor_type",
        "uploaded_by_actor_id",
    }
    assert not fields & {"storage_key", "storage_bucket", "storage_provider"}
