"""A bank mapping's values may never become a SQL identifier on trust.

`bank_mappings.mapping` is operator-supplied JSONB. The import and export code that
M4, M6 and M7 will write has to turn parts of it into column references — that is
what a mapping is for — and the moment one of those values reaches a query as an
identifier rather than as a parameter, an admin screen becomes a SQL execution
surface. Values are parameterised; identifiers cannot be, so identifiers get an
allowlist instead.

This module exists in M2, before any importer does, because the alternative is that
the first importer solves it inline and the second copies whatever the first did.

**Two independent gates, and the second is the one that matters.**

The allowlist answers "is this a field this code path is willing to touch". Callers
pass their own set, because M2 cannot know what the export columns will be — writing
a list of guessed field names here would be inventing the mapping contract several
milestones early.

The shape check answers "could this string do harm even if the allowlist were
wrong". It runs unconditionally, on the allowlisted value, after the membership
test. That ordering is deliberate: a caller who builds an allowlist from
configuration — which is exactly what a bank profile is — could otherwise widen it
by accident, and the whole point of the arrangement is that no single mistake is
sufficient.

Nothing here quotes, escapes or sanitises. A rejected identifier is refused, not
repaired: a repaired identifier is one whose meaning has changed silently, and for a
column reference that means reading the wrong column.
"""

from __future__ import annotations

import re

# Lower-case, starting with a letter, no more than 63 bytes — the PostgreSQL
# identifier limit, beyond which names are silently truncated and two fields can
# collapse into one.
_SAFE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class UnsafeIdentifierError(ValueError):
    """A mapping value cannot be used as a SQL identifier.

    A `ValueError` subclass rather than an `AppError`: reaching this is a
    programming or configuration fault, not a request a caller should be handed a
    400 for. It must surface loudly rather than becoming a field-level validation
    message somebody dismisses.
    """


def resolve_identifier(candidate: object, *, allowed: frozenset[str]) -> str:
    """Return `candidate` as a SQL identifier, or refuse it.

    `candidate` is typed `object` on purpose. It arrives from JSONB, so it may be a
    number, a list, or None, and a signature promising `str` would push the type
    error into whichever call site forgot to check.
    """

    if not allowed:
        raise UnsafeIdentifierError(
            "the allowlist is empty, so no identifier can be resolved. An empty "
            "allowlist usually means it was built from configuration that failed "
            "to load — refusing rather than falling back to 'anything'."
        )
    if not isinstance(candidate, str):
        raise UnsafeIdentifierError(
            f"a SQL identifier must be a string; got {type(candidate).__name__}. "
            "Mapping values come from JSONB and are not guaranteed to be text."
        )
    if candidate not in allowed:
        raise UnsafeIdentifierError(
            f"{candidate!r} is not an allowlisted identifier for this code path. "
            f"Permitted: {sorted(allowed)}."
        )
    # Second gate, applied after membership rather than instead of it: an allowlist
    # assembled from configuration can be widened by accident, and one mistake must
    # not be enough.
    if not _SAFE_IDENTIFIER.match(candidate):
        raise UnsafeIdentifierError(
            f"{candidate!r} is allowlisted but is not a safe identifier shape. "
            "The allowlist itself is wrong — it must contain only lower-case names "
            f"matching {_SAFE_IDENTIFIER.pattern}."
        )
    return candidate


def resolve_all(candidates: object, *, allowed: frozenset[str]) -> tuple[str, ...]:
    """Resolve a sequence of identifiers, refusing the whole set if any fails.

    All or nothing, because a partially resolved mapping is one that silently omits
    a column: an export missing a field is worse than an export that did not run.
    """

    if not isinstance(candidates, list | tuple):
        raise UnsafeIdentifierError(
            f"expected a list of identifiers; got {type(candidates).__name__}"
        )
    return tuple(resolve_identifier(item, allowed=allowed) for item in candidates)
