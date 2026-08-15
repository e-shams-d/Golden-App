"""What a file actually is, decided from its bytes.

`08_Bank_File_and_Result_Processing.md:413` states the rule this module exists for:
"File-type acceptance must use content inspection, not extension alone."
`12_Security_RBAC_Audit.md:1497-1510` lists what must be validated — signature, structural
readability, and the refusal of unknown executable and binary formats.

**The declared type and the detected type are never reconciled into one value.** M2's
model says why at `app/db/models/file_object.py`: "the comparison is the signal". A file
whose content disagrees with its label is not a file with a corrected label; it is a fact
about the upload, and collapsing the two would erase it.

**A file that fails inspection is quarantined, never deleted.** Rejection and quarantine
are different outcomes for different reasons:

  rejected     the request was malformed before anything was stored — an unknown purpose,
               a declared type the purpose does not accept, a body over the limit. There
               is nothing to keep.
  quarantined  bytes were stored and then found to be something other than claimed. That
               is evidence about whoever uploaded it, and deleting it destroys the only
               record that it happened. `12_Security_RBAC_Audit.md:1571` says
               reconciliation must not automatically delete financial evidence; the same
               principle applies at the front door.

**Detection is deliberately narrow.** It recognises the formats the purpose catalogue
accepts and the executable formats that must never be accepted, and it answers `None` for
everything else. `None` is not "probably fine" — the caller treats an undetectable type as
a quarantine reason, so a format nobody taught this module cannot arrive by default.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Final, Protocol


class Readable(Protocol):
    """Anything the upload path can stream from.

    Narrower than `BinaryIO` on purpose. The upload chains two wrappers — one captures a
    prefix, one enforces a ceiling — and neither is a file object, so typing the chain as
    `BinaryIO` would be a claim about `seek`, `tell` and a dozen other methods that
    nothing in it implements. `read` is the whole contract.
    """

    def read(self, size: int = -1, /) -> bytes: ...

# Enough for every signature below, and for a readable text sample. The prefix is
# captured while the upload streams so that detection costs no second pass over the
# bytes.
PREFIX_BYTES: Final = 8192

PNG: Final = "image/png"
JPEG: Final = "image/jpeg"
PDF: Final = "application/pdf"
XLSX: Final = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV: Final = "text/csv"

# Formats that are never acceptable, detected so the refusal can name what it found
# rather than saying only that the type was wrong. `12_Security_RBAC_Audit.md:1510`.
EXECUTABLE: Final = "application/x-executable"

_SIGNATURES: Final = (
    (b"\x89PNG\r\n\x1a\n", PNG),
    (b"\xff\xd8\xff", JPEG),
    (b"%PDF-", PDF),
    # ELF, Windows PE/COM, Mach-O in four flavours, Java class, and a shell shebang.
    # Checked before the ZIP signature because a self-extracting archive is an executable
    # first.
    (b"\x7fELF", EXECUTABLE),
    (b"MZ", EXECUTABLE),
    (b"\xfe\xed\xfa\xce", EXECUTABLE),
    (b"\xfe\xed\xfa\xcf", EXECUTABLE),
    (b"\xce\xfa\xed\xfe", EXECUTABLE),
    (b"\xcf\xfa\xed\xfe", EXECUTABLE),
    (b"\xca\xfe\xba\xbe", EXECUTABLE),
    (b"#!", EXECUTABLE),
)

# XLSX is a ZIP. The signature alone cannot tell it from any other ZIP, so the structural
# check below is what distinguishes them.
_ZIP_SIGNATURES: Final = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


class QuarantineReason:
    """Why a stored file may not become available. Recorded, never inferred later."""

    TYPE_MISMATCH: Final = "declared_and_detected_type_disagree"
    EXECUTABLE_CONTENT: Final = "executable_content"
    UNRECOGNISED_CONTENT: Final = "content_type_not_recognised"
    UNREADABLE_STRUCTURE: Final = "structurally_unreadable"


@dataclass(frozen=True)
class Inspection:
    """What the bytes turned out to be, and whether that is acceptable."""

    detected_media_type: str | None
    quarantine_reason: str | None

    @property
    def is_acceptable(self) -> bool:
        return self.quarantine_reason is None


class PrefixCapturingReader:
    """Reads through to the consumer while keeping the first `PREFIX_BYTES`.

    The prefix is taken during the upload's single pass rather than by reopening the
    object afterwards. Reopening would work, but it means the decision about what a file
    is depends on storage still holding what was just written — one more thing that can
    be true in a test and false during an incident.
    """

    def __init__(self, source: Readable) -> None:
        self._source = source
        self._prefix = bytearray()

    @property
    def prefix(self) -> bytes:
        return bytes(self._prefix)

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        if chunk and len(self._prefix) < PREFIX_BYTES:
            self._prefix.extend(chunk[: PREFIX_BYTES - len(self._prefix)])
        return chunk


def detect(prefix: bytes) -> str | None:
    """The media type the bytes claim to be, or `None` if nothing recognised them."""

    for signature, media_type in _SIGNATURES:
        if prefix.startswith(signature):
            return media_type

    if any(prefix.startswith(signature) for signature in _ZIP_SIGNATURES):
        return XLSX

    if _looks_like_text(prefix):
        return CSV

    return None


def _looks_like_text(prefix: bytes) -> bool:
    """A conservative text test, used only for CSV.

    CSV has no signature — it is text with commas — so this is the one format that cannot
    be recognised by a magic number. A NUL byte is the strongest available signal that a
    payload is not text, and refusing to decode as UTF-8 is the second. Both are cheap and
    neither guesses: anything that fails them is `None`, which quarantines.
    """

    if not prefix or b"\x00" in prefix:
        return False
    try:
        prefix.decode("utf-8")
    except UnicodeDecodeError:
        # A truncated multi-byte character at the prefix boundary is not a failure of the
        # file, so retry on a boundary-safe slice before deciding.
        try:
            prefix[: len(prefix) - 3].decode("utf-8")
        except UnicodeDecodeError:
            return False
    return True


def inspect(*, declared_media_type: str, prefix: bytes) -> Inspection:
    """Compare what was claimed against what was found.

    Returns the detected type in every case, including the failing ones: the row records
    both, and a reader asking "what was this really" must not have to guess from the
    reason string.
    """

    detected = detect(prefix)

    if detected == EXECUTABLE:
        return Inspection(detected, QuarantineReason.EXECUTABLE_CONTENT)
    if detected is None:
        return Inspection(None, QuarantineReason.UNRECOGNISED_CONTENT)
    if detected != declared_media_type:
        return Inspection(detected, QuarantineReason.TYPE_MISMATCH)
    return Inspection(detected, None)


def is_structurally_readable(media_type: str, body: BinaryIO) -> bool:
    """Whether the container opens, for the formats that have one.

    `12_Security_RBAC_Audit.md:1503` requires "image/PDF/Excel structural readability". A
    file can carry a correct signature and still be truncated or corrupt, and a bank
    statement that cannot be opened must fail here rather than three milestones later
    inside an import that assumed it could.

    Deliberately shallow: it asks whether the container is intact, not whether the content
    is meaningful. Parsing a spreadsheet's cells to decide acceptance would put a document
    parser on the upload path, and that is a much larger attack surface than the one it
    would close.
    """

    if media_type == XLSX:
        try:
            with zipfile.ZipFile(body) as archive:
                names = set(archive.namelist())
                if "[Content_Types].xml" not in names:
                    return False
                return archive.testzip() is None
        except (zipfile.BadZipFile, OSError, ValueError):
            return False

    if media_type == PDF:
        # A PDF must carry a trailer. Read the tail rather than the whole document: a
        # truncated file is the case this catches, and a truncated file has no trailer.
        try:
            body.seek(0, 2)
            size = body.tell()
            body.seek(max(0, size - 2048))
            return b"%%EOF" in body.read()
        except OSError:
            return False

    # PNG, JPEG and CSV are accepted on their signature and text test alone. An image
    # decoder on the upload path would be a larger attack surface than the corruption it
    # would detect, and a corrupt image is not a financial-integrity problem the way an
    # unreadable statement is.
    return True
