"""What an upload is allowed to be. Inlined for the runtime image.

`docs/` is not in the image, so the runtime cannot read
`docs/governance/file_purpose_catalog.yaml` — the same reason
`app/security/permission_catalogue.py` inlines the permission identifiers, and the same
arrangement: the data lives here, the decision lives in governance, and a test compares
them so the copy cannot drift.

The chain is three links and each one is gated:

    05_API_Specification.md:991-997   the seven purposes the contract offers
      -> file_purpose_catalog.yaml    what each accepts, and who may see it
        -> this module               what the runtime enforces

`FILE-PURPOSE-001` compares the first two by parsing the specification;
`test_the_inlined_copy_matches_the_catalogue` compares the last two. A purpose added in
one place and not the others fails rather than diverging quietly, which is the failure
the permission catalogue's inlined copy was built to prevent.

**Nothing here has a default-allow branch.** `accepts` and `size_limit` raise on a
purpose the catalogue does not list rather than returning a permissive answer, because
the failure mode of a file service that guesses is a file nobody meant to accept, sitting
in storage under a category nobody enumerated. `SEC-PURPOSE-001` is that test.

The extension list is deliberately *not* the acceptance rule. It exists so an upload form
can tell somebody what to pick, and so a mismatch between extension and content is
detectable — `12_Security_RBAC_Audit.md:1499-1510` requires validating both, and
`08_Bank_File_and_Result_Processing.md:413` requires that acceptance itself use content
inspection rather than the extension alone. Slice 3 is where the detected type decides;
this module only says what a purpose may contain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

# The two values `visibility_scope` may hold, and the tuple the ownership resolver is
# written against. A third value is a new access rule that something has to be taught,
# not a wider column, so the loader refuses one rather than passing it through.
VISIBILITY_SCOPES: Final = ("internal_only", "trader_visible_after_publication")

_PDF: Final = "application/pdf"
_JPEG: Final = "image/jpeg"
_PNG: Final = "image/png"
_XLSX: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CSV: Final = "text/csv"

# POL-006 is open, so these are development-only ceilings and every entry says so. The
# marker is enforced by `OPS-LIMIT-001`, which also refuses to start production while the
# limits are still these — without that refusal the marker would be a comment.
_TEN_MIB: Final = 10485760
_TWENTY_FIVE_MIB: Final = 26214400


class UnknownFilePurposeError(ValueError):
    """The purpose is not in the catalogue, so nothing may be decided about it."""


@dataclass(frozen=True, slots=True)
class FilePurpose:
    id: str
    visibility_scope: str
    accepted_media_types: frozenset[str]
    accepted_extensions: frozenset[str]
    max_bytes_development_only: int
    limits_status: str = field(default="blocked_by_POL_006")

    @property
    def is_trader_visible_after_publication(self) -> bool:
        return self.visibility_scope == "trader_visible_after_publication"


def _purpose(
    identifier: str,
    *,
    visibility_scope: str,
    media_types: tuple[str, ...],
    extensions: tuple[str, ...],
    max_bytes: int,
) -> FilePurpose:
    if visibility_scope not in VISIBILITY_SCOPES:
        raise ValueError(
            f"{identifier} declares visibility_scope {visibility_scope!r}, which is not "
            f"one of {VISIBILITY_SCOPES}. A third scope is a new access rule and needs "
            "the ownership resolver to be taught it, not a wider column."
        )
    if max_bytes <= 0:
        raise ValueError(f"{identifier} declares a non-positive size limit: {max_bytes!r}")
    return FilePurpose(
        id=identifier,
        visibility_scope=visibility_scope,
        accepted_media_types=frozenset(media_types),
        accepted_extensions=frozenset(extensions),
        max_bytes_development_only=max_bytes,
    )


# In the specification's order, which `FILE-PURPOSE-001` compares against.
_CATALOGUE: Final = (
    _purpose(
        "payment_request_source",
        visibility_scope="internal_only",
        media_types=(_PDF, _JPEG, _PNG),
        extensions=("pdf", "jpg", "jpeg", "png"),
        max_bytes=_TEN_MIB,
    ),
    _purpose(
        "incoming_payment_receipt",
        visibility_scope="trader_visible_after_publication",
        media_types=(_PDF, _JPEG, _PNG),
        extensions=("pdf", "jpg", "jpeg", "png"),
        max_bytes=_TEN_MIB,
    ),
    _purpose(
        "bank_statement",
        visibility_scope="internal_only",
        media_types=(_XLSX, _CSV),
        extensions=("xlsx", "csv"),
        max_bytes=_TWENTY_FIVE_MIB,
    ),
    _purpose(
        "bank_result_bundle_source",
        visibility_scope="internal_only",
        media_types=(_PDF, _XLSX),
        extensions=("pdf", "xlsx"),
        max_bytes=_TWENTY_FIVE_MIB,
    ),
    _purpose(
        "gold_dispatch_evidence",
        visibility_scope="trader_visible_after_publication",
        media_types=(_PDF, _JPEG, _PNG),
        extensions=("pdf", "jpg", "jpeg", "png"),
        max_bytes=_TEN_MIB,
    ),
    _purpose(
        "manual_external_evidence",
        visibility_scope="internal_only",
        media_types=(_PDF, _JPEG, _PNG),
        extensions=("pdf", "jpg", "jpeg", "png"),
        max_bytes=_TEN_MIB,
    ),
    _purpose(
        "misc_internal",
        visibility_scope="internal_only",
        media_types=(_PDF, _JPEG, _PNG, _XLSX, _CSV),
        extensions=("pdf", "jpg", "jpeg", "png", "xlsx", "csv"),
        max_bytes=_TEN_MIB,
    ),
)

PURPOSES: Final[dict[str, FilePurpose]] = {entry.id: entry for entry in _CATALOGUE}

if len(PURPOSES) != len(_CATALOGUE):  # pragma: no cover - a duplicate id is a typo
    raise ValueError("a purpose is listed twice in the inlined catalogue")


def purpose_ids() -> tuple[str, ...]:
    """The seven ids, in the specification's order."""

    return tuple(PURPOSES)


def resolve(purpose: str) -> FilePurpose:
    """The catalogue entry, or a refusal. Never a permissive default."""

    try:
        return PURPOSES[purpose]
    except KeyError:
        raise UnknownFilePurposeError(
            f"{purpose!r} is not a Phase 1A upload purpose. The seven are "
            f"{', '.join(purpose_ids())}."
        ) from None


def accepts(purpose: str, media_type: str) -> bool:
    """Whether this purpose admits this media type. An unknown purpose raises."""

    return media_type in resolve(purpose).accepted_media_types


def size_limit(purpose: str) -> int:
    """The development-only ceiling in bytes. An unknown purpose raises.

    Named `_development_only` on the dataclass and returned without that suffix here on
    purpose: a caller enforcing a limit should not have to care which regime produced the
    number, and the refusal that keeps a guessed value out of production lives in
    `Settings.validate_environment_safety` rather than at every call site.
    """

    return resolve(purpose).max_bytes_development_only


def visibility_scope(purpose: str) -> str:
    return resolve(purpose).visibility_scope
