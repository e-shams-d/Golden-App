"""Seventeen synthetic file artifacts, built from code rather than committed.

Generated, not checked in, and that is the decision worth explaining. A committed
`.pdf` is opaque: a reviewer cannot see what changed in it, a diff shows "binary
files differ", and nobody can tell a fixture edit from a corruption. Every artifact
here is built by a function whose bytes are visible in the source, so a change to a
fixture is a change a human can read.

`FIXTURE_SET_VERSION` and the manifest digest are what make them *versioned*.
`tests/backend/test_file_fixtures.py` pins the digest, so editing any artifact fails
until the version is bumped deliberately. A silently altered fixture is worse than a
missing one: the tests still pass and no longer test what they say.

**Nothing here is a live threat.** In particular there is no EICAR string. The real
EICAR test file is designed to be detected, which means a developer's antivirus or a
CI runner's scanner would quarantine it — deleting the fixture, breaking the build,
and in the worst case flagging the repository. The suspicious-file case uses a
clearly synthetic marker that no scanner recognises, because what the test needs is
a file the *simulated* scanner reports on, not one a real scanner reacts to.

The formula-injection case is the one that matters most in this codebase. Iranian
bank exports are consumed in Excel, and a cell beginning `=`, `+`, `-`, `@`, or with
a leading tab or carriage return, is executed by the spreadsheet rather than
displayed. That is a live path from a trader-supplied filename to code running on an
accountant's workstation.
"""

from __future__ import annotations

import hashlib
import zlib
from dataclasses import dataclass, field
from pathlib import Path

# Bumped whenever any artifact's bytes or metadata change. The digest test refuses
# a change that does not bump it.
FIXTURE_SET_VERSION = "1"


@dataclass(frozen=True)
class FileFixture:
    """One artifact, plus what it is for and what it should be called on upload."""

    name: str
    content: bytes
    declared_mime: str
    # The filename as a hostile or careless client would send it. Never used to
    # build a storage key — `generate_storage_key` ignores it entirely — so the
    # traversal and control-character cases are here to prove that.
    upload_filename: str
    purpose: str
    detected_mime: str | None = None
    expected_scan: str = "clean"
    tags: frozenset[str] = field(default_factory=frozenset)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.content)


def _pdf(body: str) -> bytes:
    """A minimal structurally valid PDF. Small, parseable, and not a real document."""

    return (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        + body.encode("utf-8")
        + b"\ntrailer<</Root 1 0 R>>\n%%EOF\n"
    )


def _png(width: int, height: int) -> bytes:
    """A valid single-colour PNG, assembled with correct CRCs.

    Built rather than embedded so the magic bytes, the chunk framing and the CRCs
    are all visible — which is what makes the "PNG bytes named .pdf" fixture a real
    mismatch rather than a string that happens to start with the right characters.
    """

    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return len(payload).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _xlsx() -> bytes:
    """A ZIP-shaped artifact with the OOXML signature bytes.

    Not a workbook Excel would open — it does not need to be. What the tests use it
    for is the container signature, so that "declared xlsx, detected zip" and
    "truncated xlsx" are distinguishable.
    """

    return b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 18 + b"[Content_Types].xml"


# The seventeen. Each one earns its place by making a specific test possible.
FIXTURES: tuple[FileFixture, ...] = (
    FileFixture(
        name="valid_pdf_receipt",
        content=_pdf("% an ordinary receipt"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="رسید-واریز.pdf",
        purpose="the ordinary case, and a Persian filename that must survive round-tripping",
    ),
    FileFixture(
        name="duplicate_pdf_receipt",
        content=_pdf("% an ordinary receipt"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="رسید-واریز (کپی).pdf",
        purpose="byte-identical to valid_pdf_receipt: the duplicate-checksum condition",
        tags=frozenset({"duplicate_checksum"}),
    ),
    FileFixture(
        name="corrupt_pdf_truncated",
        content=b"%PDF-1.4\n1 0 obj<</Type/Catalog",
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="نیمه-کاره.pdf",
        purpose="right header, no trailer: a transfer that stopped midway",
        tags=frozenset({"corrupt"}),
    ),
    FileFixture(
        name="pdf_with_javascript_marker",
        content=_pdf("4 0 obj<</Type/Action/S/JavaScript/JS(app.alert(1))>>endobj"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="فرم-تعاملی.pdf",
        purpose="a scanner-relevant marker inside a valid PDF; not executable here",
        expected_scan="quarantined",
        tags=frozenset({"suspicious"}),
    ),
    FileFixture(
        name="valid_xlsx_statement",
        content=_xlsx(),
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        detected_mime="application/zip",
        upload_filename="صورت-حساب.xlsx",
        purpose="OOXML is a ZIP, so declared and detected legitimately differ",
        tags=frozenset({"container"}),
    ),
    FileFixture(
        name="corrupt_xlsx_truncated",
        content=b"PK\x03\x04\x14\x00",
        declared_mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        detected_mime="application/zip",
        upload_filename="صورت-حساب-خراب.xlsx",
        purpose="ZIP magic with no central directory",
        tags=frozenset({"corrupt"}),
    ),
    FileFixture(
        name="png_named_as_pdf",
        content=_png(2, 2),
        declared_mime="application/pdf",
        detected_mime="image/png",
        upload_filename="رسید.pdf",
        purpose="the extension/MIME mismatch: the reason the two columns are separate",
        tags=frozenset({"mime_mismatch"}),
    ),
    FileFixture(
        name="valid_png_photo",
        content=_png(4, 4),
        declared_mime="image/png",
        detected_mime="image/png",
        upload_filename="عکس-بارنامه.png",
        purpose="a source a crop derives from",
    ),
    FileFixture(
        name="valid_jpeg_photo",
        # SOI, a minimal APP0/JFIF segment, then EOI.
        content=(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"),
        declared_mime="image/jpeg",
        detected_mime="image/jpeg",
        upload_filename="عکس-حواله.jpg",
        purpose="the other image container, so detection is not tested against one format",
    ),
    FileFixture(
        name="formula_injection_csv",
        content=(
            "شرح,مبلغ\r\n"
            "=cmd|' /C calc'!A0,1000\r\n"
            "+1+1,2000\r\n"
            "-2+3,3000\r\n"
            "@SUM(1+9),4000\r\n"
            "\t=1+1,5000\r\n"
            "\r=1+1,6000\r\n"
        ).encode("utf-8"),
        declared_mime="text/csv",
        detected_mime="text/csv",
        upload_filename="لیست-پرداخت.csv",
        purpose=(
            "all six injection prefixes Excel executes; a live path from a trader "
            "upload to code on an accountant's workstation"
        ),
        tags=frozenset({"formula_injection"}),
    ),
    FileFixture(
        name="empty_file",
        content=b"",
        declared_mime="application/octet-stream",
        detected_mime="application/x-empty",
        upload_filename="خالی.dat",
        purpose="zero bytes: why size_bytes is >= 0 and not > 0",
        tags=frozenset({"edge_size"}),
    ),
    FileFixture(
        name="single_byte_file",
        content=b"\x00",
        declared_mime="application/octet-stream",
        detected_mime="application/octet-stream",
        upload_filename="یک-بایت.dat",
        purpose="one byte, and that byte is a NUL: the off-by-one either side of empty",
        tags=frozenset({"edge_size"}),
    ),
    FileFixture(
        name="persian_text_with_zero_width_joiner",
        content="می‌رود به بانک‌\n".encode(),
        declared_mime="text/plain",
        detected_mime="text/plain",
        upload_filename="یادداشت.txt",
        purpose="ZWNJ, which normalisation strips and byte comparison does not",
        tags=frozenset({"unicode"}),
    ),
    FileFixture(
        name="filename_attempting_traversal",
        content=_pdf("% ordinary content, hostile name"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="../../../etc/passwd",
        purpose="the filename is the payload; the storage key must not contain any of it",
        tags=frozenset({"hostile_filename"}),
    ),
    FileFixture(
        name="filename_with_control_characters",
        # A distinct body from the traversal fixture: identical content would make
        # these two an unintended duplicate-checksum pair, and the duplicate
        # detector's test asserts there is exactly one such pair on purpose.
        content=_pdf("% ordinary content, control characters in the name"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="receipt\r\n\x00.pdf",
        purpose="CR, LF and NUL in a filename: header injection and truncation attempts",
        tags=frozenset({"hostile_filename"}),
    ),
    FileFixture(
        name="filename_at_maximum_length",
        content=_pdf("% ordinary content, very long name"),
        declared_mime="application/pdf",
        detected_mime="application/pdf",
        upload_filename="ب" * 250 + ".pdf",
        purpose="255 characters of Persian, which is more than 255 bytes in UTF-8",
        tags=frozenset({"edge_length"}),
    ),
    FileFixture(
        name="simulated_suspicious_marker",
        # Deliberately NOT the EICAR string. A real EICAR file would be quarantined
        # by a developer's antivirus or a CI runner's scanner, which deletes the
        # fixture and breaks the build. What the tests need is a file the simulated
        # scanner reports on.
        content=b"SYNTHETIC-NOT-A-VIRUS-MARKER-FOR-GOLDEN-APP-TESTS-ONLY\n",
        declared_mime="text/plain",
        detected_mime="text/plain",
        upload_filename="مشکوک.txt",
        purpose="the simulated suspicious scanner result, with nothing a real scanner reacts to",
        expected_scan="quarantined",
        tags=frozenset({"suspicious"}),
    ),
)

FIXTURES_BY_NAME: dict[str, FileFixture] = {fixture.name: fixture for fixture in FIXTURES}


def manifest_digest() -> str:
    """A digest over every artifact's bytes and metadata.

    Covers the metadata as well as the content, because changing a fixture's
    declared MIME type changes what a test asserts just as surely as changing its
    bytes does.
    """

    digest = hashlib.sha256()
    digest.update(FIXTURE_SET_VERSION.encode("utf-8"))
    for fixture in FIXTURES:
        for part in (
            fixture.name,
            fixture.declared_mime,
            fixture.detected_mime or "",
            fixture.upload_filename,
            fixture.expected_scan,
            ",".join(sorted(fixture.tags)),
        ):
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        digest.update(len(fixture.content).to_bytes(8, "big"))
        digest.update(fixture.content)
    return digest.hexdigest()


def materialise(root: Path) -> dict[str, Path]:
    """Write every artifact under `root`, returning name → path.

    For the tests that need a real file on disk rather than bytes in memory —
    streaming reads, and the storage backend's own write path.
    """

    root.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for fixture in FIXTURES:
        # Named by fixture name, never by `upload_filename`: two of those are
        # hostile and one is 250 characters of Persian.
        path = root / f"{fixture.name}.bin"
        path.write_bytes(fixture.content)
        written[fixture.name] = path
    return written
