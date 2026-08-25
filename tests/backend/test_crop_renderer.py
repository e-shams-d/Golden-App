"""The renderer's properties, asserted rather than claimed in a comment.

M8 slice 4. `pyproject.toml` says this dependency reproduces a crop byte for byte and validates
rotation; M7 established that such a claim belongs in a test against real output, not in prose next
to a version number. These are those tests.

Pure functions over bytes, so no database and no fixtures on disk: the PDF is built in memory,
because a binary fixture is a thing nobody reads and the point is to measure the library.

Covers: SVC-CROP-004.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from app.exports.crop import (
    CROP_MEDIA_TYPE,
    PERMITTED_ROTATIONS,
    RENDER_SCALE,
    RENDERER_VERSION,
    CropRefused,
    Rectangle,
    page_count,
    page_size,
    render_crop,
)

# A two-page PDF, written by hand. Small enough to read, and it exercises the only two things the
# crop path needs from a document: more than one page, and a known page size.
TWO_PAGES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R 5 0 R]/Count 2>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 4 0 R"
    b"/Resources<</Font<</F1 7 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT /F1 24 Tf 20 300 Td (PAGE ONE) Tj ET\n"
    b"endstream endobj\n"
    b"5 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 400]/Contents 6 0 R"
    b"/Resources<</Font<</F1 7 0 R>>>>>>endobj\n"
    b"6 0 obj<</Length 44>>stream\n"
    b"BT /F1 24 Tf 20 300 Td (PAGE TWO) Tj ET\n"
    b"endstream endobj\n"
    b"7 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
)

A_RECTANGLE = Rectangle(
    x=Decimal("0.105000"),
    y=Decimal("0.220000"),
    width=Decimal("0.500000"),
    height=Decimal("0.300000"),
)


def test_the_document_opens_and_reports_its_pages() -> None:
    """The control. Every assertion below is vacuous against a document that will not open."""

    assert page_count(TWO_PAGES) == 2
    assert page_size(TWO_PAGES, 1) == (600, 800)
    # 300x400 points at scale 2.0. Asserted so a scale change is a visible edit rather than a
    # silent change to every stored crop's provenance.
    assert RENDER_SCALE == 2.0


def test_the_same_rectangle_renders_byte_identically() -> None:
    """`SVC-CROP-004`, and the assertion that makes Q-3's stricter reading legitimate.

    §16.6 asks for reproduction "within approved tolerance" and no document approves one. If two
    renders of one rectangle are identical there is nothing to approve — so this is what lets the
    plan assert byte equality instead of inventing a number.
    """

    first = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=0)
    second = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=0)

    assert first.content == second.content
    assert first.content, "an empty crop would make the comparison above meaningless"
    assert first.media_type == CROP_MEDIA_TYPE


def test_a_rotated_crop_is_reproducible_and_different() -> None:
    """DOC-CONFLICT-057, demonstrated rather than argued.

    Two claims in one test because they are two halves of one point: rotation *changes* the crop —
    so a stored rectangle without its angle describes a different region — and a rotated crop is
    itself reproducible, so storing the angle is sufficient.
    """

    upright = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=0)
    turned = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=90)
    again = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=90)

    assert turned.content != upright.content, (
        "rotation did not change the crop, so DOC-CONFLICT-057's premise would be wrong"
    )
    assert turned.content == again.content
    # The raster's own dimensions swap, which is why the same normalised rectangle lands elsewhere.
    assert (turned.source_pixel_width, turned.source_pixel_height) == (
        upright.source_pixel_height,
        upright.source_pixel_width,
    )


def test_the_provenance_is_recorded_with_the_bytes() -> None:
    """Everything `receipt_segments` needs to make this crop again comes back from the renderer.

    A crop whose row cannot say which renderer produced it is one nobody can reproduce after an
    upgrade — and the version is both halves, because either the wrapper or the pdfium build
    changing can change a pixel.
    """

    rendered = render_crop(TWO_PAGES, page_number=2, rectangle=A_RECTANGLE, rotation_degrees=180)

    assert rendered.renderer_version == RENDERER_VERSION
    assert "pypdfium2/" in rendered.renderer_version
    assert "pdfium/" in rendered.renderer_version
    assert rendered.rotation_degrees == 180
    assert rendered.source_pixel_width > 0
    assert rendered.crop_pixel_width > 0


@pytest.mark.parametrize(
    ("label", "rectangle"),
    [
        ("zero width", Rectangle(Decimal("0.1"), Decimal("0.1"), Decimal("0"), Decimal("0.2"))),
        (
            "negative origin",
            Rectangle(Decimal("-0.1"), Decimal("0.1"), Decimal("0.2"), Decimal("0.2")),
        ),
        (
            "past the right edge",
            Rectangle(Decimal("0.6"), Decimal("0.1"), Decimal("0.5"), Decimal("0.2")),
        ),
        (
            "past the bottom edge",
            Rectangle(Decimal("0.1"), Decimal("0.9"), Decimal("0.2"), Decimal("0.2")),
        ),
    ],
)
def test_an_unreproducible_rectangle_is_refused(label: str, rectangle: Rectangle) -> None:
    """§16.4's "validate normalized rectangle", before the page is rendered.

    The database refuses these too — §12.4's CHECK — and both matter: the CHECK is what holds for
    every writer, and this is what gives the caller a message naming the problem instead of a
    constraint name, and what stops a page render being spent on a rectangle that cannot be stored.
    """

    with pytest.raises(CropRefused):
        render_crop(TWO_PAGES, page_number=1, rectangle=rectangle, rotation_degrees=0)

    assert label


@pytest.mark.parametrize("rotation", [45, 1, -90, 360])
def test_an_angle_no_preview_can_produce_is_refused(rotation: int) -> None:
    """§16.4's "and rotation". `08_...Processing.md:985` gives clockwise and counter-clockwise
    rotation, which produces exactly four angles — so an arbitrary one could never be reproduced by
    the control that is supposed to have created it."""

    with pytest.raises(CropRefused):
        render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=rotation)

    assert rotation not in PERMITTED_ROTATIONS


def test_a_missing_page_is_refused_rather_than_rendered_blank() -> None:
    """A crop of page 9 of a 2-page document is not an empty image; it is a mistake.

    Returning a blank would produce a stored file and a row claiming evidence — the shape this
    milestone guards against everywhere else.
    """

    with pytest.raises(CropRefused):
        render_crop(TWO_PAGES, page_number=9, rectangle=A_RECTANGLE, rotation_degrees=0)
    with pytest.raises(CropRefused):
        render_crop(TWO_PAGES, page_number=0, rectangle=A_RECTANGLE, rotation_degrees=0)


def test_a_rectangle_that_rounds_away_is_refused() -> None:
    """The edge the CHECK cannot see.

    §12.4 admits any positive width, but a rectangle 1/100000th of a page wide rounds to zero pixels
    at this scale. The database would store the row happily; the file would prove nothing. Refused
    here because this is the only place that knows the render scale.
    """

    sliver = Rectangle(
        x=Decimal("0.100000"),
        y=Decimal("0.100000"),
        width=Decimal("0.000001"),
        height=Decimal("0.300000"),
    )

    with pytest.raises(CropRefused):
        render_crop(TWO_PAGES, page_number=1, rectangle=sliver, rotation_degrees=0)


def test_the_png_carries_no_timestamp() -> None:
    """Why the byte-equality claim holds at all.

    Pillow will write the clock into a PNG chunk if asked, and two renders of one rectangle would
    then never match. Asserted by looking for the chunk rather than by comparing twice, because the
    comparison above would pass if both runs happened inside the same second.
    """

    rendered = render_crop(TWO_PAGES, page_number=1, rectangle=A_RECTANGLE, rotation_degrees=0)

    assert b"tIME" not in rendered.content


# An odd-sized page. Rounding is the only place a computed size and a rendered one can diverge, and
# 300x400 divides evenly at scale 2.0 — so the even case cannot detect the mistake.
ODD_PAGE = TWO_PAGES.replace(b"MediaBox[0 0 300 400]", b"MediaBox[0 0 301 399]")


@pytest.mark.parametrize("document", [TWO_PAGES, ODD_PAGE], ids=["even", "odd"])
@pytest.mark.parametrize("rotation", PERMITTED_ROTATIONS)
def test_the_computed_page_size_is_the_rendered_page_size(document: bytes, rotation: int) -> None:
    """`page_size` computes rather than renders, and this is what makes that safe.

    The request path asks for a page's raster dimensions to check them against what the operator's
    screen reported. Rendering the page to answer would put the one expensive operation — a whole
    page raster — on the synchronous path the crop job exists to keep it off. So the size is
    computed from the page's points, and the two must agree exactly: a size one pixel off would
    reject every crop on that page as drawn against the wrong raster, with a message blaming the
    client.

    Both orientations and an odd page size, because that is where rounding would show.
    """

    computed = page_size(document, 1, rotation=rotation)
    rendered = render_crop(
        document,
        page_number=1,
        rectangle=A_RECTANGLE,
        rotation_degrees=rotation,
    )

    assert computed == (rendered.source_pixel_width, rendered.source_pixel_height)


def test_the_page_size_of_a_page_that_is_not_there_is_refused() -> None:
    """The same refusal as the renderer's, because the request path asks this first.

    Returning a size for a page that does not exist would let a crop be accepted against imaginary
    dimensions and fail only in the worker, where the operator never sees the reason.
    """

    with pytest.raises(CropRefused):
        page_size(TWO_PAGES, 9)
    with pytest.raises(CropRefused):
        page_size(TWO_PAGES, 1, rotation=45)
