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
import unicodedata

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

# Iranian IBAN, as the database stores it. `app/db/models/bank.py` holds the same
# expression as `IBAN_PATTERN` for the CHECK constraint, and
# `tests/backend/test_identifiers.py` asserts the two agree — the convention this
# repository already uses for `ACCOUNT_STATUSES_SQL` and `BENEFICIARY_STATUSES_SQL`.
# Importing the model here instead would pull SQLAlchemy into a module that exists
# to turn strings into strings.
_IBAN = re.compile("^IR[0-9]{24}$")

# Local copies of `app/core/hashing.py`'s folding tables. Copied rather than
# imported for the reason `normalize_person_name` records: that module's rules
# serve content hashing and may change for content-hashing reasons, while this
# result is written into a column. `tests/backend/test_identifiers.py` asserts they
# agree today, so a divergence is a decision somebody makes rather than one that
# happens.
_ARABIC_TO_PERSIAN = {
    "ي": "ی",  # ARABIC YEH -> FARSI YEH
    "ى": "ی",  # ALEF MAKSURA -> FARSI YEH
    "ك": "ک",  # ARABIC KAF -> KEHEH
    "ۀ": "ه",  # HEH WITH YEH ABOVE -> HEH
}

_ZERO_WIDTH = {"‌", "‍", "‎", "‏", "﻿"}

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


def normalize_iban(value: str) -> str:
    """Return the stored form of an Iranian IBAN: `IR` then twenty-four digits.

    The same reasoning as `normalize_mobile`, applied to a payment destination
    rather than a login. A trader typing into a Persian interface produces Persian
    digits, and banks print IBANs in four-character groups, so the ordinary input
    has both non-ASCII digits and spaces in it. Storing what was typed would mean
    two spellings of one account, and the duplicate warning this feeds would then
    miss the duplicate it exists to find.

    `iban` keeps what the trader typed, for display. This is what anything
    compares.

    The shape is checked here and *also* by a CHECK constraint on the column; the
    check digits are checked only here. A mod-97 remainder is not something a
    readable CHECK expression computes, and the two rules sit at different levels
    on purpose: the database refuses a string that is not an IBAN at all, and the
    application refuses one that is shaped like an IBAN and cannot be one.
    """

    folded = _SEPARATORS.sub("", fold_digits(value)).strip().upper()

    if not folded:
        raise InvalidIdentifier("the IBAN is empty after normalisation")

    if not _IBAN.match(folded):
        raise InvalidIdentifier(
            "not an Iranian IBAN: expected IR followed by twenty-four digits"
        )

    if _iso_7064_remainder(folded) != 1:
        raise InvalidIdentifier(
            "the IBAN's check digits do not match the rest of it; one of the "
            "twenty-six characters is mistyped"
        )

    return folded


def _iso_7064_remainder(iban: str) -> int:
    """The mod-97 remainder ISO 13616 requires to be 1.

    Four characters move from the front to the back, letters become two digits
    each (`A` is 10, so `I` is 18 and `R` is 27), and the result read as one
    integer must leave 1 on division by 97. Python's arbitrary-precision integers
    make the whole thing four lines; the piecewise form other languages need is
    only there to avoid a twenty-six-digit number.

    **This is what the check digits are for.** Without it a single mistyped digit
    produces an IBAN that passes every validation in this system, reaches a
    beneficiary record, is snapshotted onto a payment request, and leaves in the
    bank export — money addressed to an account nobody chose. Two IBANs differing
    only in their check digits were both accepted before this, and at most one of
    any such pair can be correct.

    Not imported from a library: `schwifty` and friends carry country registries
    and bank directories this project has no use for, and the rule itself is
    stable — ISO 13616 has not changed the algorithm since 1997.
    """

    rearranged = iban[4:] + iban[:4]
    numeric = "".join(
        str(ord(character) - 55) if character.isalpha() else character
        for character in rearranged
    )
    return int(numeric) % 97


def normalize_person_name(value: str) -> str:
    """A name folded to one spelling, for search and duplicate detection.

    Deliberately **not** `app.core.hashing.normalise_text`, which does almost the
    same thing. That function exists to make two spellings of a name hash alike,
    and its rules may change for hashing reasons. This result is *stored* in
    `beneficiaries.normalized_name`, so a change there would leave every existing
    row folded by the old rule and every new one by the new rule — and the
    duplicate warning would quietly stop matching rows it used to match. Two
    functions that agree today and can diverge deliberately beat one that couples
    a stored column to a content-hashing decision.

    The Arabic-to-Persian letter folding is the part that earns its place in Iran:
    `ي` and `ی`, `ك` and `ک` are different code points that render nearly
    identically, and the same person's name arrives spelled both ways depending on
    the keyboard.

    Case-folded, because `Ali Example` and `ali example` are one person. Returns
    an empty string rather than raising: a name that folds to nothing is a
    detection helper with nothing to say, not an invalid identity, and
    `full_name` carries the real value.
    """

    folded = unicodedata.normalize("NFC", value)
    folded = "".join(character for character in folded if character not in _ZERO_WIDTH)
    folded = fold_digits(folded)
    for source, target in _ARABIC_TO_PERSIAN.items():
        folded = folded.replace(source, target)
    return " ".join(folded.split()).casefold()
