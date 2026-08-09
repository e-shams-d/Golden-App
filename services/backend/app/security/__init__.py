"""Authentication and session mechanics, with no HTTP in any of it.

`12_Security_RBAC_Audit.md:377` requires domain services to stay
transport-neutral and consume an authenticated `ActorContext` rather than
transport-specific claims. That is a structural rule here, not an aspiration:
`tests/backend/test_actor_context.py` fails if anything in this package imports
`fastapi`, `starlette` or `app.api`.

The reason is ADR-001. It approved cookie-carried server-side sessions, and the
approval records that the choice stays reversible behind this interface. An
interface that reaches for a `Request` is not reversible — it is the transport,
spelled differently.
"""

from __future__ import annotations
