"""Scoping a query to the caller's own trader, so it cannot be written otherwise.

`14_Testing_QA_Acceptance.md:1274-1284` lists seven mandatory IDOR cases, and one
of them names the attack this module exists to stop: *"Trader A submits
`trader_id` belonging to B"*. The defence is not to validate that field — it is to
never read it. Ownership arrives from `ActorContext.trader_id`, which came from
`trader_users.trader_id` via the session cookie, and nothing a caller sends can
reach it.

**Why a helper rather than a convention.** "Remember the `WHERE trader_id = ?`"
is the kind of rule that holds until the day someone adds a listing endpoint in a
hurry. `scoped()` makes the predicate the only way to build the query, and
`SVC-SCOPE-001` fails the build on a repository function that returns owned rows
without going through it. A rule a reviewer enforces is a rule that lapses; a rule
the type system and a gate enforce does not.

**Not-mine and not-existing answer identically.** `:1284` requires refusal
"without disclosing whether the target exists where appropriate", and for a
trader-owned resource that is always appropriate: a 404-versus-403 difference over
sequential or guessable identifiers is an enumeration oracle. So `require_owned`
raises the same `NotFoundError` for a row that belongs to somebody else as for a
row that is not there.

**An internal actor is not an owner.** `12_Security_RBAC_Audit.md:316` says an
internal session must not be treated as ownership of a trader account unless an
explicitly authorized support workflow exists. There is no such workflow in Phase
1A, so an admin scoping through this module is a programming error rather than a
wide read — the alternative, letting an admin silently see everything through the
ownership path, is how "trader A's data leaked into an admin response" happens
(`:1282`).

Covers: SEC-IDOR-001, SEC-IDOR-002, SEC-IDOR-005, SVC-SCOPE-001.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute

from app.core.errors import NotFoundError
from app.security.actor import ActorContext


class OwnershipScopeError(RuntimeError):
    """Raised when the scope itself is unusable — a bug, not a denial.

    Distinct from `NotFoundError` on purpose. A denial is an answer to a caller;
    this is a statement that the code asked an incoherent question, and turning it
    into a 404 would hide a wiring mistake behind a plausible-looking response.
    """


def scoped[Row](
    statement: Select[tuple[Row]],
    column: InstrumentedAttribute[uuid.UUID],
    actor: ActorContext,
) -> Select[tuple[Row]]:
    """Restrict a query to rows the actor owns.

    Takes the actor rather than a `trader_id` so there is no parameter a caller's
    value could be passed into. That is the whole design: the mandatory IDOR case
    is not "validate the submitted trader_id", it is "have no argument to submit
    it to".
    """

    if not actor.is_trader:
        raise OwnershipScopeError(
            "ownership scoping was asked for a non-trader actor. Doc 12:316 forbids "
            "treating an internal session as ownership of a trader account without an "
            "authorized support workflow, and Phase 1A has none. An internal listing "
            "must apply its own filter and its own permission, not this."
        )
    if actor.trader_id is None:  # pragma: no cover - ActorContext already refuses this
        raise OwnershipScopeError("a trader actor without a trader_id cannot be scoped")

    return statement.where(column == actor.trader_id)


def require_owned(row: object | None, owner_id: uuid.UUID | None, actor: ActorContext) -> object:
    """Return the row, or refuse indistinguishably from it not existing.

    Used for a fetch by primary key, where the scope cannot be pushed into the
    query because the identifier is the whole request. The refusal must not reveal
    which of the two happened.
    """

    if row is None or not actor.owns(owner_id):
        raise NotFoundError()
    return row
