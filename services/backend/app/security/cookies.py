"""Cookie names, attributes and CSRF tokens — as values, not as HTTP calls.

ADR-001 approved cookie-carried server-side sessions. What that means concretely
is decided here; *setting* the header is the router's job, so this module stays
importable from the transport-free half of the codebase and
`SVC-ACTOR-001` keeps holding.

**`__Host-` is doing real work, not decoration.** A browser refuses to store a
cookie with that prefix unless it is `Secure`, carries **no** `Domain`, and has
`Path=/`. That is exactly the combination this deployment needs, and having the
client enforce it is stronger than setting the attributes correctly ourselves,
because an attribute we set is one a later edit can change.

The isolation axis here is the **host**, not the path. `infra/nginx/conf.d/local.conf`
serves the trader app on `trader.localhost` and the admin app on
`admin.localhost`, each same-origin with its own `/api/` proxy. A host-only cookie
is never sent to the sibling app. Path cannot express this: the API is
resource-first with no audience segment, and a path-scoped cookie would miss the
shared `/auth/*` routes and the separate `/files/` prefix entirely.

The footgun `__Host-` closes is concrete, and the way it closes it is worth stating
precisely, because an earlier version of this comment got it wrong.

`server_name trader.localhost localhost` binds the trader app to bare `localhost` as
well, so *an ordinary cookie* set with `Domain=localhost` would be delivered to
`admin.localhost` too — and in production `Domain=example.ir` would leak the trader
cookie to the admin app. What the prefix does is make that unreachable: the browser
**refuses to store the cookie at all** rather than storing it too widely. The
distinction matters because it decides what a test can assert. This comment used to
say the wide delivery "would" happen, which reads as though the leak is the failure
mode to guard against; the actual failure mode is a session that silently never
exists, and a control written against the first one passes while testing nothing.

Measured in Chromium rather than assumed —
`apps/trader-pwa/tests/platform/cookie-prefix.spec.ts`, `UI-ISO-003`:

    STORED    __Host-correct=1; Secure; Path=/
    REJECTED  __Host-with-domain=1; Secure; Path=/; Domain=localhost
    REJECTED  __Host-no-secure=1; Path=/
    REJECTED  __Host-narrow-path=1; Secure; Path=/somewhere
    STORED    ordinary-with-domain=1; Path=/; Domain=localhost

The last line is what makes the second one meaningful: an ordinary cookie carrying the
same `Domain` *is* stored, so the refusal is caused by the prefix and not by the
attribute being invalid.

That test also settles a deployment question this module's `secure=True` raises.
`isSecureContext` is true on plain-HTTP `localhost`, so the unconditional `Secure`
flag does not force TLS into the local stack — and no environment switch is needed to
avoid it, which is the outcome to prefer: a flag that relaxed the prefix in
development would mean local runs exercised a different cookie contract than
production.

**`SameSite` is not audience isolation.** `trader.example.ir` and
`admin.example.ir` are the same *site*, so `SameSite` says nothing about them. It
is set to `Strict` because it defends against third-party sites, which is a
different and also necessary job.

**CSRF is bound to the session and validated server-side**, as
`12_Security_RBAC_Audit.md:495` requires — not a stateless double-submit, which
only proves that two attacker-writable values match. The token is an HMAC of the
session's stored digest under a server key, so it cannot be produced without the
key, it changes when the session rotates, and it needs no extra storage or
lookup.

Binding to the stored digest rather than to the session id matters: `/auth/me`
returns the session id, so a token derived from the id would be derivable by
anyone who ever saw one `me` response together with the key. The digest is
server-side only and never leaves the database.

Covers: SEC-CSRF-001.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Literal

from app.security.actor import Audience

# `__Host-` forces Secure + no Domain + Path=/. The names differ per audience so
# a browser holding both never has to choose, and so an admin request carries no
# trader credential even on a shared host.
ADMIN_SESSION_COOKIE = "__Host-gp_admin_session"
TRADER_SESSION_COOKIE = "__Host-gp_trader_session"

# Readable by script on purpose: the page has to put it in a header, and a header
# is the part an attacker's cross-site form cannot set. The session cookie stays
# HttpOnly; this one carries no authority on its own.
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

CSRF_HEADER = "X-CSRF-Token"

# The prefix's requirements, kept here so a route cannot set a `__Host-` cookie
# with attributes the browser will silently reject.
COOKIE_PATH = "/"

# Typed as the literal Starlette accepts rather than a bare `str`, so a typo
# reaches mypy instead of reaching a browser that silently ignores the attribute.
COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "strict"


@dataclass(frozen=True, slots=True)
class CookieNames:
    session: str
    csrf: str


def names_for(audience: Audience) -> CookieNames:
    if audience is Audience.ADMIN:
        return CookieNames(session=ADMIN_SESSION_COOKIE, csrf=ADMIN_CSRF_COOKIE)
    return CookieNames(session=TRADER_SESSION_COOKIE, csrf=TRADER_CSRF_COOKIE)


def csrf_token(secret_digest: str, key: bytes) -> str:
    """A token bound to one session, unforgeable without the server key.

    Recomputed on every unsafe request from the session that was just
    authenticated, so validation is a comparison against a value the server
    derived rather than a lookup of something a client stored.
    """

    if not key:
        raise ValueError(
            "the CSRF key is empty, so the token would be a plain hash of a value "
            "the server already holds — forgeable by anyone who learns the digest"
        )
    return hmac.new(key, secret_digest.encode("ascii"), hashlib.sha256).hexdigest()


def csrf_token_matches(presented: str | None, secret_digest: str, key: bytes) -> bool:
    """Constant-time comparison, and `None` is a mismatch rather than an error.

    `compare_digest` because a naive `==` on a hex string leaks, through timing,
    how many leading characters were right — which is enough to construct a valid
    token one character at a time.
    """

    if not presented:
        return False
    return hmac.compare_digest(presented, csrf_token(secret_digest, key))


# Methods that may not change state, so they carry no CSRF requirement.
# `12_Security_RBAC_Audit.md:497` separately prohibits state-changing GETs, which
# is what makes this list safe to treat as exhaustive.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def requires_csrf(method: str) -> bool:
    return method.upper() not in SAFE_METHODS
