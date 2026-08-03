"""Redaction applied before the insert, never after.

Audit rows cannot be updated — the runtime role has no UPDATE privilege on
`audit_logs`, by migration. That is the whole reason this runs at write time. A
read-time mask would leave the raw value in the row forever, visible to anything
holding a direct connection or a backup, and the only remedy would be deleting
evidence.

Two categories, deliberately different in kind:

*Absolute prohibitions* (`04_Database_Schema.md:1470`) are settled and are
enforced here now. A password, session secret, raw token, raw idempotency key or
storage credential never reaches the column, whatever the caller passed.

*Policy masking* — per-role IBAN visibility — is **parameterised, not decided**.
POL-003 is open. This module takes the policy as an argument and applies it; it
does not contain one. Writing a default here would decide an open question by
shipping it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

REDACTED = "[REDACTED]"

# Matched against the key, case-insensitively, as a substring. Substring rather
# than equality because the real risk is `user_password`, `x_api_token` and
# `storage_secret_access_key`, not a field someone helpfully named `password`.
PROHIBITED_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "session_id_raw",
    "idempotency_key",
    "authorization",
    "cookie",
    "file_content",
    "content_bytes",
)

# An allow-list that wins over the fragments above, for names that contain a
# prohibited fragment but hold a digest rather than the value itself. Without
# this, `idempotency_key_hash` — a column that exists precisely so the raw key is
# never stored — would be redacted, and the audit row would lose the one safe
# identifier it is allowed to keep.
DIGEST_SUFFIXES: tuple[str, ...] = ("_hash", "_digest", "_fingerprint")

MAX_REDACTION_DEPTH = 12

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


@dataclass(frozen=True)
class RedactionPolicy:
    """What the caller's role is allowed to see. No defaults are chosen here.

    `mask_iban` is supplied per call site because POL-003 has not settled which
    roles see a full IBAN. Passing it explicitly keeps the open decision visible
    at every point that depends on it, instead of hiding it in a default that
    reads as approved.
    """

    mask_iban: bool

    def apply_to_text(self, value: str) -> str:
        if not self.mask_iban:
            return value
        return _IBAN.sub(lambda match: mask_iban_value(match.group(0)), value)


def mask_iban_value(value: str) -> str:
    """Keep the country prefix and the last four digits, hide the account.

    Enough to reconcile a record against a statement, not enough to originate a
    transfer from the audit trail.
    """

    stripped = value.replace(" ", "")
    if len(stripped) <= 8:
        return REDACTED
    return f"{stripped[:4]}{'*' * (len(stripped) - 8)}{stripped[-4:]}"


def is_prohibited_key(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith(DIGEST_SUFFIXES):
        return False
    return any(fragment in lowered for fragment in PROHIBITED_KEY_FRAGMENTS)


def redact(value: Any, policy: RedactionPolicy, *, _depth: int = 0) -> Any:
    """Return a copy of `value` safe to persist in an audit column.

    Recursion is bounded. A payload deep enough to exhaust the stack would turn a
    redaction failure into a crash inside the command, and the safe answer at
    that depth is to store nothing rather than to store it unredacted.
    """

    if _depth > MAX_REDACTION_DEPTH:
        return REDACTED

    if isinstance(value, Mapping):
        return {
            str(key): (
                REDACTED
                if is_prohibited_key(str(key))
                else redact(item, policy, _depth=_depth + 1)
            )
            for key, item in value.items()
        }

    # str is a Sequence; checking it first stops a string being walked character
    # by character into a list.
    if isinstance(value, str):
        return policy.apply_to_text(value)

    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [redact(item, policy, _depth=_depth + 1) for item in value]

    if isinstance(value, bytes | bytearray):
        # Raw file content is an absolute prohibition and a length is harmless,
        # so record the shape rather than the bytes.
        return f"{REDACTED} ({len(value)} bytes)"

    return value
