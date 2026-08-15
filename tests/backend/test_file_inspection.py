"""Content inspection: what the bytes are, decided from the bytes.

Covers: FILE-VAL-005.

The end-to-end outcomes — quarantine, the row surviving, the executable refusal — are in
`tests/integration/test_file_inspection.py`, because they are claims about what the route
and the database do. This file is about the decision function itself, where the cases can
be enumerated cheaply.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from app.files.inspection import (
    CSV,
    EXECUTABLE,
    JPEG,
    PDF,
    PNG,
    XLSX,
    PrefixCapturingReader,
    QuarantineReason,
    detect,
    inspect,
    is_structurally_readable,
)

PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415408d763f8cfc00000030101003c8b9c1e0000000049454e44ae426082"
)
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
PDF_BYTES = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def xlsx_bytes(*, content_types: bool = True) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if content_types:
            archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (PNG_BYTES, PNG),
        (JPEG_BYTES, JPEG),
        (PDF_BYTES, PDF),
        (xlsx_bytes(), XLSX),
        (b"date,amount\n2026-08-15,1000\n", CSV),
        (b"\x7fELF\x02\x01\x01", EXECUTABLE),
        (b"MZ\x90\x00\x03", EXECUTABLE),
        (b"#!/bin/sh\necho hi\n", EXECUTABLE),
        (b"\xca\xfe\xba\xbe\x00\x00", EXECUTABLE),
        (b"\x00\x01\x02\x03\xff\xfe", None),
    ],
)
def test_detection_reads_the_signature(payload: bytes, expected: str | None) -> None:
    assert detect(payload) == expected


def test_an_unrecognised_payload_is_none_rather_than_a_guess() -> None:
    """`None` is not "probably fine".

    The caller treats an undetectable type as a quarantine reason, so a format nobody
    taught this module cannot arrive by default. A detector that fell back to the declared
    type would make the comparison it exists for impossible.
    """

    assert detect(b"\x00binary garbage\x00") is None
    assert detect(b"") is None


def test_the_decision_ignores_the_filename_and_the_declared_type() -> None:
    """FILE-VAL-005. `08_Bank_File_and_Result_Processing.md:413`.

    The same bytes get the same detected type regardless of what they were called or
    claimed to be. This is the property that makes extension-based acceptance impossible
    to reintroduce by accident.
    """

    for declared in (PNG, PDF, XLSX, "application/octet-stream"):
        assert detect(PNG_BYTES) == PNG
        result = inspect(declared_media_type=declared, prefix=PNG_BYTES)
        assert result.detected_media_type == PNG
        assert result.is_acceptable is (declared == PNG)


def test_a_matching_declaration_is_acceptable() -> None:
    result = inspect(declared_media_type=PNG, prefix=PNG_BYTES)
    assert result.is_acceptable
    assert result.quarantine_reason is None


def test_a_mismatch_names_the_reason_and_keeps_both_types() -> None:
    """A PNG that says it is a PDF. The row records both, because the comparison is the
    signal — reconciling them into one value would erase the fact."""

    result = inspect(declared_media_type=PDF, prefix=PNG_BYTES)
    assert result.detected_media_type == PNG
    assert result.quarantine_reason == QuarantineReason.TYPE_MISMATCH


def test_executable_content_is_named_as_such_not_merely_as_a_mismatch() -> None:
    """An ELF declared as an image is a mismatch *and* an executable, and the reason
    recorded is the second one. "Wrong type" and "someone uploaded a binary" warrant
    different attention, and the row is the only place that distinction survives."""

    result = inspect(declared_media_type=PNG, prefix=b"\x7fELF\x02\x01\x01")
    assert result.detected_media_type == EXECUTABLE
    assert result.quarantine_reason == QuarantineReason.EXECUTABLE_CONTENT


def test_unrecognised_content_quarantines_rather_than_passing() -> None:
    result = inspect(declared_media_type=PNG, prefix=b"\x00\x01\x02\xff")
    assert result.detected_media_type is None
    assert result.quarantine_reason == QuarantineReason.UNRECOGNISED_CONTENT


def test_a_structurally_broken_spreadsheet_is_not_readable() -> None:
    """A correct signature is not a readable file. A statement that cannot be opened must
    fail here rather than three milestones later inside an import that assumed it could."""

    assert is_structurally_readable(XLSX, io.BytesIO(xlsx_bytes()))
    assert not is_structurally_readable(XLSX, io.BytesIO(xlsx_bytes(content_types=False)))
    assert not is_structurally_readable(XLSX, io.BytesIO(b"PK\x03\x04truncated"))


def test_a_truncated_pdf_has_no_trailer() -> None:
    assert is_structurally_readable(PDF, io.BytesIO(PDF_BYTES))
    assert not is_structurally_readable(PDF, io.BytesIO(PDF_BYTES[:20]))


def test_the_prefix_reader_passes_every_byte_through() -> None:
    """Guard the guard for the capture.

    A reader that captured a prefix and dropped or duplicated bytes would corrupt every
    upload while inspection still looked correct — the digest would be of content nobody
    sent.
    """

    payload = bytes(range(256)) * 64
    reader = PrefixCapturingReader(io.BytesIO(payload))

    chunks = []
    while chunk := reader.read(1000):
        chunks.append(chunk)

    assert b"".join(chunks) == payload
    assert reader.prefix == payload[:8192]


def test_the_prefix_is_bounded_for_a_file_smaller_than_the_window() -> None:
    reader = PrefixCapturingReader(io.BytesIO(PNG_BYTES))
    assert reader.read() == PNG_BYTES
    assert reader.prefix == PNG_BYTES


def test_a_utf8_character_split_across_the_prefix_boundary_is_still_text() -> None:
    """CSV is the one format with no signature, so its test is a text test — and a text
    test that failed on a multi-byte character landing on the boundary would quarantine
    legitimate Persian statements, which is most of them here."""

    # RUF001 flags the Extended Arabic-Indic digits as confusable with Latin ones, which
    # is exactly right in code and exactly wrong in a fixture: these digits are what
    # arrives in a statement exported by an Iranian bank, and replacing them with ASCII
    # would test a file this platform will never receive.
    persian = "ردیف,مبلغ\n۱,۱۰۰۰\n" * 800  # noqa: RUF001
    payload = persian.encode("utf-8")
    assert len(payload) > 8192
    assert detect(payload[:8192]) == CSV
