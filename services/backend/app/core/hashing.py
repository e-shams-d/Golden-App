"""Content hashing that still matches years later, on a different interpreter.

Every hash column in the system is compared against a value computed at a
different time, by a different process, possibly on a different Python. M7
compares an export hash against a batch-version hash against an approval hash —
if any of those disagree for a reason other than the content differing, an
approved batch cannot be exported and nobody can say why.

So determinism here is not "the same input gives the same output in this run".
It is: the same *meaning* gives the same digest across library upgrades,
interpreter versions, dict insertion orders and platform locales.

**Prohibited as inputs**, because each is stable only by accident:

* `hash()` — randomised per process by PYTHONHASHSEED.
* `repr()` — a formatting decision that upstream libraries change freely.
* Python dict ordering — insertion-ordered, and the insertion order of a parsed
  JSON body is the sender's, not ours.
* `json.dumps` defaults — non-ASCII escaping, separator spacing and key order all
  change the bytes without changing the meaning.

**The algorithm carries a version.** A stored digest is compared against one
computed by code that may have changed. Without a version, an intentional
improvement to normalisation silently invalidates every stored hash and the
failure appears as "the export does not match its approval".

**Persian and Arabic text is normalised.** The same name typed with an Arabic
kaf/yeh (ك/ي) and a Persian one (ک/ی) is the same name to a reader and different
bytes to a hash, and both appear routinely in Iranian banking data. Zero-width
joiners are stripped for the same reason, and digits are folded to ASCII so
۱۲۳ and 123 hash alike.
"""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

# Bump only with a migration plan for existing stored digests. A change here
# means every previously stored hash was computed by a different algorithm, and
# comparing across the boundary is meaningless rather than merely wrong.
CANONICAL_HASH_VERSION = "v1"

_ALGORITHM = "sha256"

# Arabic forms that Persian text uses interchangeably. Unicode NFC does not
# unify these — they are distinct characters — so the mapping is explicit.
_ARABIC_TO_PERSIAN = {
    "ي": "ی",  # ARABIC YEH -> FARSI YEH
    "ى": "ی",  # ALEF MAKSURA -> FARSI YEH
    "ك": "ک",  # ARABIC KAF -> KEHEH
    "ۀ": "ه",  # HEH WITH YEH ABOVE -> HEH
}

# Zero-width joiner and non-joiner: invisible, meaningful for rendering, and
# routinely present or absent in the same name from two sources.
_ZERO_WIDTH = {"‌", "‍", "‎", "‏", "﻿"}

_PERSIAN_DIGITS = {ord("۰") + index: ord("0") + index for index in range(10)}
_ARABIC_DIGITS = {ord("٠") + index: ord("0") + index for index in range(10)}


class CanonicalisationError(ValueError):
    """A value that cannot be represented deterministically.

    Raised rather than coerced. A float here would hash to something stable and
    wrong: 0.1 + 0.2 does not equal 0.3, so two amounts a human calls equal
    produce different digests.
    """


def normalise_text(value: str) -> str:
    """One spelling per meaning, for text that reaches a hash."""

    normalised = unicodedata.normalize("NFC", value)
    normalised = "".join(
        character for character in normalised if character not in _ZERO_WIDTH
    )
    normalised = normalised.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)
    for source, target in _ARABIC_TO_PERSIAN.items():
        normalised = normalised.replace(source, target)
    # Collapse runs of whitespace: two sources rendering the same name with one
    # or two spaces must agree.
    return " ".join(normalised.split())


def canonical(value: Any) -> Any:
    """Reduce a value to a form with exactly one representation.

    Recursive, and deliberately narrow: an unexpected type raises rather than
    falling back to `str()`, which would make the digest depend on whatever
    `__str__` happened to produce.
    """

    if value is None or isinstance(value, bool):
        return value

    if isinstance(value, int):
        return value

    if isinstance(value, float | Decimal):
        raise CanonicalisationError(
            f"{type(value).__name__} cannot be hashed deterministically. Money is "
            "integer IRR; other quantities must be integers or strings before "
            "they reach a hash."
        )

    if isinstance(value, str):
        return normalise_text(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise CanonicalisationError(
                "a naive datetime has no single instant, so two systems in "
                "different zones would hash the same wall clock differently"
            )
        # UTC, microsecond precision, fixed format. `isoformat()` alone varies:
        # it omits microseconds when they are zero, which makes a value hash
        # differently depending on whether it round-tripped through a database.
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    if isinstance(value, Enum):
        return canonical(value.value)

    if isinstance(value, Mapping):
        # Sorted by key, so insertion order — which for a parsed request body is
        # the sender's choice — cannot change the digest.
        return {
            normalise_text(str(key)): canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }

    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        # Order preserved: a list is ordered data, and reordering rows changes
        # what a batch means.
        return [canonical(item) for item in value]

    raise CanonicalisationError(
        f"{type(value).__name__} has no canonical form. Convert it explicitly "
        "rather than letting str() decide, which makes the digest depend on a "
        "formatting choice."
    )


def canonical_bytes(value: Any) -> bytes:
    """The exact bytes that get hashed.

    Serialised by hand rather than through `json.dumps`, whose defaults —
    separator spacing, non-ASCII escaping, key order — are formatting choices
    that upstream is free to change.
    """

    def render(node: Any) -> str:
        if node is None:
            return "n"
        if isinstance(node, bool):
            return "b:1" if node else "b:0"
        if isinstance(node, int):
            return f"i:{node}"
        if isinstance(node, str):
            # Length-prefixed, so "a" + "bc" cannot collide with "ab" + "c".
            return f"s:{len(node.encode('utf-8'))}:{node}"
        if isinstance(node, dict):
            return "{" + ",".join(f"{render(k)}={render(v)}" for k, v in node.items()) + "}"
        if isinstance(node, list):
            return "[" + ",".join(render(item) for item in node) + "]"
        raise CanonicalisationError(f"unrenderable canonical node: {type(node).__name__}")

    return render(canonical(value)).encode("utf-8")


def content_hash(value: Any) -> str:
    """A versioned digest: `v1:<sha256 hex>`.

    The version is part of the returned string rather than stored separately, so
    a comparison between digests computed under different algorithms fails as a
    mismatch instead of appearing to succeed.
    """

    digest = hashlib.new(_ALGORITHM, canonical_bytes(value)).hexdigest()
    return f"{CANONICAL_HASH_VERSION}:{digest}"


def parameters_hash(parameters: Mapping[str, Any]) -> str:
    """A digest over derivation inputs, for reproducibility rather than identity.

    Preferred to a uniqueness constraint over raw JSONB: two payloads that differ
    only in key order are the same derivation, and a unique index on the JSONB
    would treat them as different.
    """

    return content_hash(dict(parameters))


def hashes_match(stored: str, computed: str) -> bool:
    """Compare two digests, refusing to compare across algorithm versions.

    Returning False for a version mismatch would read as "the content changed",
    which sends an operator looking for a difference that is not there.
    """

    stored_version = stored.split(":", 1)[0]
    computed_version = computed.split(":", 1)[0]
    if stored_version != computed_version:
        raise ValueError(
            f"cannot compare a {stored_version!r} digest with a {computed_version!r} "
            "one: they were produced by different algorithms, so equality and "
            "inequality both mean nothing."
        )
    return stored == computed
