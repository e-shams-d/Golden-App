"""The `auth_events` writer: what was denied, failed, or attempted.

`auth_events` is not `audit_logs`, and the split is load-bearing. Audit explains
an authorised change and attaches to an entity; a security event explains a
refusal, has no entity, and frequently has no actor either — a failed login for a
username that does not exist is the case that matters most and the one an
actor-bearing schema cannot record. Their retention, their read permissions and
their alerting all differ.

**Secret material is kept out by construction, not by care.** The metadata column
accepts only the keys in `ALLOWED_METADATA_KEYS`; anything else raises. A denylist
would have to anticipate every name a future caller invents, and the first one it
failed to anticipate would be written to an append-only table with no DELETE
grant. `04_Database_Schema.md:444` forbids storing plaintext passwords, OTPs,
tokens or full secrets here.

**The session digest is not recordable either**, which is less obvious. The digest
*is* the stored lookup key, so a log dump plus a database dump would let someone
join a recorded probe to a live session row. Where a rejected secret matched no
session and there is no id to record, a truncated second-order digest is used for
correlation only.

**Nothing is written on a successful validation.** That would be one append-only
row per API request, forever, on a table the runtime may never delete from.
Session lifecycle transitions are recorded; per-request access belongs to
`audit_logs` and to metrics.

Covers: SEC-EVENT-001.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from app.db.models.session_and_security import ACTOR_TYPES, EVENT_CLASSES

# Every key the metadata column may carry, with the reason it is safe. An
# allowlist rather than a denylist: the failure mode of a denylist is a key
# nobody thought of, written permanently.
ALLOWED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "rejection_reason",  # a SessionRejection value; describes the server's verdict
        "audience",  # admin or trader; derived server-side
        "auth_level",  # `password`; no secret is implied by the factor's name
        "replaced_session_id",  # a session id, which is not a credential
        "stamp_session",  # integers, useful only for diagnosing a stamp mismatch
        "stamp_identity",
        "probe_correlation",  # truncated second-order digest; see `probe_correlation`
        "reason",  # a revocation reason, drawn from the code's own vocabulary
    }
)

# `outcome` has no CHECK on the column, but `idx_auth_events_failures` is partial
# on `outcome <> 'success'`, so the spelling of success is load-bearing: a typo
# would silently move a successful event into the failures index.
OUTCOME_SUCCESS = "success"
OUTCOME_FAILURE = "failure"
OUTCOME_DENIED = "denied"
OUTCOME_ERROR = "error"

OUTCOMES: tuple[str, ...] = (OUTCOME_SUCCESS, OUTCOME_FAILURE, OUTCOME_DENIED, OUTCOME_ERROR)

# `metadata_schema` and `metadata_version` are both NOT NULL with no default, and
# `FINANCIAL_INTEGRITY_BASELINE.md` §4 requires JSON metadata to carry both so a
# reader can tell which shape it is looking at.
METADATA_SCHEMA = "auth_event.session.v1"
METADATA_VERSION = 1

# `auth_events.user_agent` is VARCHAR(512). Truncating here rather than
# letting the insert fail: an over-long header is itself a signal worth
# recording, and losing the event to record it is the wrong trade.
USER_AGENT_LENGTH = 512


class DisallowedEventMetadata(ValueError):
    """Raised before an insert, naming the key and not its value.

    Naming the value would defeat the purpose: the exception text is the next
    place a secret would leak, after the column this check exists to protect.
    """


@dataclass(frozen=True, slots=True)
class SecurityEvent:
    """One row of `auth_events`, validated before it can be built.

    A frozen dataclass rather than keyword arguments threaded to an insert, so
    the validation cannot be skipped by a caller who builds the row directly.
    """

    actor_type: str
    event_type: str
    event_class: str
    outcome: str
    actor_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    # `auth_events` carries both columns (`04_Database_Schema.md:442`) and this
    # writer could not populate either until M3 slice 7. Every security event
    # written before then has NULL for where the attempt came from, which is the
    # first thing an investigator looks for. Added as first-class fields rather
    # than as metadata keys because a typed column survives a metadata schema
    # change and a JSON key does not.
    #
    # Both are attacker-controlled and neither is used for authorization — they
    # are recorded so a pattern can be seen, and nothing reads them to decide
    # anything.
    ip_address: str | None = None
    user_agent: str | None = None
    metadata_payload: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.actor_type not in ACTOR_TYPES:
            raise ValueError(
                f"actor_type {self.actor_type!r} is not one of {ACTOR_TYPES}; "
                "ck_auth_events_actor_type would reject the insert"
            )
        if self.event_class not in EVENT_CLASSES:
            raise ValueError(
                f"event_class {self.event_class!r} is not one of {EVENT_CLASSES}; "
                "ck_auth_events_event_class would reject the insert"
            )
        if self.outcome not in OUTCOMES:
            raise ValueError(
                f"outcome {self.outcome!r} is not one of {OUTCOMES}. The spelling matters "
                "beyond tidiness: idx_auth_events_failures is partial on "
                "outcome <> 'success'."
            )
        if not self.event_type.strip():
            raise ValueError("event_type must not be blank, as ck_auth_events_event_type requires")

        disallowed = sorted(set(self.metadata_payload or {}) - ALLOWED_METADATA_KEYS)
        if disallowed:
            raise DisallowedEventMetadata(
                f"these metadata keys are not on the allowlist: {disallowed}. "
                "auth_events is append-only and the runtime holds no DELETE grant, so a "
                "credential written here cannot be removed. Add the key to "
                "ALLOWED_METADATA_KEYS only after deciding it carries no secret."
            )

    def as_row(self) -> dict[str, Any]:
        """The insert payload, with both metadata descriptors always present."""

        return {
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "event_type": self.event_type,
            "event_class": self.event_class,
            "outcome": self.outcome,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            # Truncated to the column width rather than left to PostgreSQL to
            # reject: a 4KB user-agent header is a request that fails at the
            # insert, and the insert in question is often the one recording the
            # attack that sent it.
            "user_agent": (self.user_agent or None) and self.user_agent[:USER_AGENT_LENGTH],
            "metadata_payload": dict(self.metadata_payload or {}),
            "metadata_schema": METADATA_SCHEMA,
            "metadata_version": METADATA_VERSION,
        }


def probe_correlation(secret_digest: str) -> str:
    """A short second-order digest, for correlating repeated probes.

    Hashing the digest again matters. The digest itself is the value stored in
    `auth_sessions.secret_hash`, so recording it would let anyone holding both a
    log export and a database export join a rejected probe to a live session.
    Hashing once more breaks that join while still letting two rejections of the
    same presented secret be recognised as the same secret.

    Truncated because the only question it answers is "was this the same one
    again", and a full digest of a value that never matched is more retained data
    than that question needs.
    """

    return hashlib.sha256(secret_digest.encode("ascii")).hexdigest()[:16]
