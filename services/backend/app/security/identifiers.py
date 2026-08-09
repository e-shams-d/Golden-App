"""Turning what a person typed into the one identifier the database stores.

A login identity has to have exactly one spelling, or uniqueness means nothing.
`09123456789`, `+989123456789`, `0912 345 6789` and `۰۹۱۲۳۴۵۶۷۸۹` are the same
human, and if they reach `trader_users.phone_number` as four different strings
then `UNIQUE (phone_number)` permits four accounts for one person — and a rate
limit keyed on the identifier counts four separate budgets for one attacker.

**Persian and Arabic-Indic digits are the case that must not be forgotten.**
Iranian keyboards produce `۰۹۱۲…` by default, so a trader typing their own number
into a Persian interface is the *ordinary* path, not an edge case. A normaliser
that only handles ASCII would reject the most common input in the deployment
country and look, from the outside, like "the site says my number is wrong".

**Only Iranian mobile numbers are accepted, and that is a decision.** The platform
is deployed only in Iran; the trader interface is a PWA; and a login identity that
cannot receive a message is one that ADR-009 could never build step-up
authentication on. A landline would also commonly be shared by an office, which
is the opposite of what an identity is for. If the owner wants to admit landlines
or foreign numbers, this is the one place to change, and no stored data has to
move — registration does not exist before slice 8.

This module deliberately does not reuse `app.core.hashing.normalise_text`. That
function exists to make two spellings of a *name* hash alike, and it collapses
whitespace and strips joiners for that purpose. Sharing it would tie the login
identity's meaning to a content-hashing rule, so a later change made for
document hashing would silently change who can sign in.

Covers: SEC-IDENT-001.
"""

from __future__ import annotations

import re

# Iranian mobile numbers are `9` followed by nine digits, on operator prefixes
# 90-99. Written locally with a leading `0`, internationally as +98.
_MOBILE_NATIONAL = re.compile(r"^9\d{9}$")

# Everything a human might put between digits. Written as escapes rather than as
# literal characters because most of these are invisible: pasted Persian text
# routinely carries zero-width and bidirectional marks, and a literal in the
# source would be an unreviewable blank space that a later edit could delete
# without anyone noticing.
_SEPARATORS = re.compile(
    "[\\s\\-().]"
    "|[‌-‏]"  # ZWNJ, ZWJ, LRM, RLM
    "|[‪-‮]"  # bidirectional embedding and override marks
    "|﻿"  # byte-order mark, which pasted text often carries
)

_PERSIAN_DIGITS = {ord("۰") + index: ord("0") + index for index in range(10)}
_ARABIC_DIGITS = {ord("٠") + index: ord("0") + index for index in range(10)}

# The stored form. E.164 because it is unambiguous, because it is what any
# messaging provider ADR-009 might later choose will expect, and because a stored
# `0` prefix is a national convention that means nothing without a country.
COUNTRY_CODE = "+98"


class InvalidIdentifier(ValueError):
    """Raised only where the caller can act on it.

    Never surfaced to an unauthenticated client: a login endpoint that
    distinguished "that is not a valid number" from "wrong password" would answer
    a question the generic-error rule exists to refuse
    (`12_Security_RBAC_Audit.md:403`).
    """


def fold_digits(value: str) -> str:
    """Map Persian and Arabic-Indic digits onto ASCII.

    Applied before anything else looks at the string, because every check below
    is written in terms of ASCII digits and a Persian `۹` is not `9` to a regular
    expression.
    """

    return value.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def normalize_mobile(value: str) -> str:
    """Return the E.164 form of an Iranian mobile number.

    Raises `InvalidIdentifier` rather than returning `None`: every caller must
    decide what to do about an unusable identifier, and an `Optional` return is
    the shape that gets `or ""`-ed into a lookup that then matches nothing and
    reports "wrong password".
    """

    folded = _SEPARATORS.sub("", fold_digits(value)).strip()

    if not folded:
        raise InvalidIdentifier("the identifier is empty after normalisation")

    # Strip whichever way the country code was written, leaving the national
    # significant number. Order matters: `0098` must be tried before `0`.
    for prefix in ("+98", "0098", "98", "0"):
        if folded.startswith(prefix):
            folded = folded[len(prefix) :]
            break

    if not _MOBILE_NATIONAL.match(folded):
        raise InvalidIdentifier(
            "not an Iranian mobile number: expected nine digits after a leading 9, "
            "written as 09xxxxxxxxx or +989xxxxxxxxx"
        )

    return f"{COUNTRY_CODE}{folded}"


def normalize_username(value: str) -> str:
    """The admin login identifier.

    `admin_users.username` is `CITEXT`, so PostgreSQL already compares without
    regard to case and no lowering happens here — doing it twice would be a
    second rule that could drift from the column's.

    What the column does *not* do is trim, and `  accountant1 ` is a paste
    artefact rather than a different person. Digits are folded for the same
    reason as above: a username containing a Persian digit would otherwise be
    unreachable from a keyboard that produces the ASCII one.
    """

    normalized = fold_digits(value).strip()
    if not normalized:
        raise InvalidIdentifier("the username is empty after normalisation")
    return normalized
