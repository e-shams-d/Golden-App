"""Who may reach a file, decided per category, with no default.

`12_Security_RBAC_Audit.md:1530-1539` requires every download and preview request to
re-evaluate session state, permission, object scope, file category, lifecycle and scan
state, publication state for trader access, and any restriction. A route guard covers the
permission; this module covers the rest, and it is the half that a permission alone cannot
express — `file.download` says an actor may download *some* file, never *this* one.

**A category with no registered resolver is denied.** There is no default branch, no
fallback and no "internal actors may see anything". That is the property M4's Definition of
Done rests on: a later module attaches files to its own resource by registering a resolver
for its category, and until it does, nothing can be downloaded under that category by
anyone. `SEC-FILEDL-003` is the test, and it is the one that fails if a permissive default
is ever added.

**Ownership does not run through `file_links`.** Document 12 asks for business ownership to
be represented explicitly rather than by trusting a client field, and M2 scoped
`file_links` to non-critical attachments with an instruction not to promote it into a
general link primitive. The critical owning resources — payment requests, batches, bundles
— do not exist until M5 to M8 and will carry their own foreign keys. So in M4 the only
ownership fact available is who uploaded the file, and the resolvers say exactly that
rather than inventing a relationship.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.files.purposes import purpose_ids
from app.security.actor import ActorContext

# Held by staff who may read a mixed internal bundle. Named here because the sensitive
# resolver is the one place a second permission is required beyond the route's guard.
SENSITIVE_BUNDLE_PERMISSION: Final = "file.read_sensitive_bundle"


@dataclass(frozen=True)
class FileFacts:
    """What a resolver is allowed to know about the file.

    Deliberately not the ORM row. A resolver that could reach the whole model could reach
    `storage_key`, and the boundary M4 exists to draw is that a storage address stays
    inside the file service. Passing the four facts an ownership decision needs makes the
    wider access impossible rather than merely discouraged.
    """

    category: str
    visibility_scope: str
    uploaded_by_actor_type: str
    uploaded_by_actor_id: uuid.UUID | None


Resolver = Callable[[ActorContext, FileFacts], bool]


def _is_internal(actor: ActorContext) -> bool:
    """Staff, by the actor's own domain rather than by role name.

    `trader_id is None` is M3's recorded definition of "owns nothing", which is the
    correct answer for staff. Testing the audience instead would ask where the request
    arrived from, which is a different question and one an attacker has more influence
    over.
    """

    return actor.actor_type.value == "admin_user"


def internal_only(actor: ActorContext, file: FileFacts) -> bool:
    """Staff may reach it; a trader never may, whoever uploaded it.

    Used for statements and internal working files. A statement covers every trader at
    once, which is why no trader may read one even if a trader somehow uploaded it.
    """

    del file
    return _is_internal(actor)


def sensitive_internal_bundle(actor: ActorContext, file: FileFacts) -> bool:
    """A mixed bank bundle: staff only, and only with the explicit sensitive grant.

    `15_Agent_Implementation_Plan.md:721` names this exact case as an M4 test — a trader
    cannot download an internal bank bundle. The extra permission is what makes it
    narrower than `internal_only`: a bundle mixes many traders' results in one document,
    so reading it is a decision about all of them.
    """

    del file
    return _is_internal(actor) and SENSITIVE_BUNDLE_PERMISSION in actor.permissions


def uploader_or_internal(actor: ActorContext, file: FileFacts) -> bool:
    """Staff, plus the trader who uploaded this exact file.

    The comparison is against the *stored* uploader, never against anything the request
    carries. A trader who uploaded a payment-request source may read it back; another
    trader may not, and the file does not become readable to them because they know its
    id.
    """

    if _is_internal(actor):
        return True
    return (
        file.uploaded_by_actor_type == actor.actor_type.value
        and file.uploaded_by_actor_id is not None
        and file.uploaded_by_actor_id == actor.actor_id
    )


def published_or_uploader(actor: ActorContext, file: FileFacts) -> bool:
    """Staff, the uploading trader, and — once publication exists — a published trader.

    M4 builds no publication, so for any other trader this is a refusal today. It is
    written as a refusal rather than left absent so that M9 turns an existing check into
    an allowance instead of discovering there was never one. `SEC-FILEDL-005` asserts the
    refusal, and it is the test M9 must edit rather than add.
    """

    return uploader_or_internal(actor, file)


# One entry per catalogued purpose, each written out rather than defaulted. A purpose
# added to the catalogue without a line here is denied to everyone — which is the
# behaviour worth having, and slice 11's Definition-of-Done gate turns it into a failing
# test rather than a silent refusal in production.
_RESOLVERS: Final[dict[str, Resolver]] = {
    "payment_request_source": uploader_or_internal,
    "incoming_payment_receipt": published_or_uploader,
    "bank_statement": internal_only,
    "bank_result_bundle_source": sensitive_internal_bundle,
    "gold_dispatch_evidence": published_or_uploader,
    "manual_external_evidence": internal_only,
    "misc_internal": internal_only,
}


def resolver_for(category: str) -> Resolver | None:
    """The resolver, or `None`. `None` means denied — never "allowed by default"."""

    return _RESOLVERS.get(category)


def may_access(actor: ActorContext, file: FileFacts) -> bool:
    """The whole ownership decision, and the only entry point.

    Written so that the deny path is the fall-through: if the lookup misses, the function
    returns `False` without consulting anything else. An implementation that raised here
    instead would be equally safe until somebody caught the exception.
    """

    resolver = resolver_for(file.category)
    if resolver is None:
        return False
    return resolver(actor, file)


def categories_with_a_resolver() -> frozenset[str]:
    """For the gates that check every catalogued purpose has one."""

    return frozenset(_RESOLVERS)


def categories_without_a_resolver() -> frozenset[str]:
    return frozenset(purpose_ids()) - categories_with_a_resolver()
