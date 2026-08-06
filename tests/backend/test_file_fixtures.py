"""The fixture set is versioned, and this is what makes that claim true.

A test fixture that changes silently is worse than a missing one: the suite still
passes and no longer tests what its name says. So the manifest digest is pinned
here. Editing any artifact's bytes or metadata fails this test until
`FIXTURE_SET_VERSION` is bumped, which turns a fixture change into a deliberate,
reviewable act.

The coverage assertions below exist because "seventeen fixtures" is not the
requirement — the requirement is that specific conditions are representable. A set
of seventeen valid PDFs would satisfy a count and prove nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from file_fixtures import (
    FIXTURE_SET_VERSION,
    FIXTURES,
    FIXTURES_BY_NAME,
    manifest_digest,
    materialise,
)

# Bumped together with FIXTURE_SET_VERSION, never on its own.
PINNED_DIGEST = "8109ecc734ad215938ff57a38b99ed6ed827635c5c824fb4f65776ddad583458"

# The conditions the plan requires be representable. Each maps to a tag rather than
# to a fixture name, so a fixture can be renamed or replaced without weakening what
# is being asserted.
REQUIRED_TAGS = frozenset(
    {
        "mime_mismatch",
        "corrupt",
        "formula_injection",
        "duplicate_checksum",
        "suspicious",
        "hostile_filename",
        "edge_size",
        "unicode",
    }
)


def test_there_are_exactly_seventeen() -> None:
    assert len(FIXTURES) == 17


def test_names_are_unique() -> None:
    """A duplicate name would silently shadow one artifact with another in the
    by-name mapping every test uses."""

    assert len(FIXTURES_BY_NAME) == len(FIXTURES)


def test_the_manifest_digest_is_pinned(pytestconfig: pytest.Config) -> None:
    """Fails on any fixture edit until the version and this digest are both updated.

    The failure message carries the new digest, so the intended workflow is: change
    the fixture, bump `FIXTURE_SET_VERSION`, paste the digest, and the diff shows all
    three together.
    """

    computed = manifest_digest()

    assert computed == PINNED_DIGEST, (
        f"the fixture set changed. Version is {FIXTURE_SET_VERSION!r}; bump it and "
        f"set PINNED_DIGEST to:\n{computed}"
    )


@pytest.mark.parametrize("tag", sorted(REQUIRED_TAGS))
def test_every_required_condition_is_represented(tag: str) -> None:
    assert [fixture.name for fixture in FIXTURES if tag in fixture.tags], (
        f"no fixture is tagged {tag!r}, so that condition cannot be tested"
    )


def test_the_duplicate_shares_a_digest_with_its_original() -> None:
    """FILE-META-005 depends on this being byte-identical, not merely similar."""

    original = FIXTURES_BY_NAME["valid_pdf_receipt"]
    duplicate = FIXTURES_BY_NAME["duplicate_pdf_receipt"]

    assert original.sha256 == duplicate.sha256
    assert original.upload_filename != duplicate.upload_filename


def test_no_two_other_fixtures_collide_by_accident() -> None:
    """Exactly one intended duplicate pair. Two artifacts colliding unintentionally
    would make the duplicate-detection test pass for the wrong reason."""

    digests = [fixture.sha256 for fixture in FIXTURES]

    assert len(set(digests)) == len(FIXTURES) - 1


def test_the_mismatch_fixture_really_is_one_format_named_as_another() -> None:
    fixture = FIXTURES_BY_NAME["png_named_as_pdf"]

    assert fixture.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert fixture.upload_filename.endswith(".pdf")
    assert fixture.declared_mime == "application/pdf"
    assert fixture.detected_mime == "image/png"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_the_injection_fixture_covers_every_prefix_excel_executes(prefix: str) -> None:
    """All six, because a sanitiser that handles `=` and misses `@` is a sanitiser
    that looks like it works.

    Split on the literal `\\r\\n` terminator rather than with `splitlines()`:
    `splitlines` treats a bare `\\r` as a line break, so it would consume the very
    prefix this test is checking for and the `\\r` case would pass vacuously.
    """

    content = FIXTURES_BY_NAME["formula_injection_csv"].content.decode("utf-8")
    cells = [cell for row in content.split("\r\n") for cell in row.split(",")]

    assert any(cell.startswith(prefix) for cell in cells)


def test_no_fixture_contains_the_eicar_string() -> None:
    """A real EICAR file would be quarantined by a developer's antivirus or a CI
    runner's scanner, deleting the fixture and breaking the build.

    Asserted by reconstructing the signature at runtime rather than writing it as a
    literal — a literal in this file would itself be the thing scanners react to.
    """

    signature = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR" + b"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

    for fixture in FIXTURES:
        assert signature not in fixture.content
        assert b"EICAR" not in fixture.content


def test_the_empty_fixture_is_actually_empty() -> None:
    """The `size_bytes >= 0` case. A one-byte "empty" file would not test it."""

    assert FIXTURES_BY_NAME["empty_file"].size_bytes == 0


def test_materialise_writes_every_artifact(tmp_path: Path) -> None:
    written = materialise(tmp_path / "files")

    assert set(written) == set(FIXTURES_BY_NAME)
    for name, path in written.items():
        assert path.read_bytes() == FIXTURES_BY_NAME[name].content


def test_materialise_never_uses_the_upload_filename(tmp_path: Path) -> None:
    """Two upload filenames are hostile and one is 250 Persian characters. Writing
    them to a real path is how a test suite creates the vulnerability it is
    supposed to be checking for."""

    written = materialise(tmp_path / "files")

    for path in written.values():
        assert path.parent == tmp_path / "files"
        assert path.suffix == ".bin"
