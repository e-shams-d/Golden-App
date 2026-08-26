"""The renderer's properties, asserted rather than claimed in a comment.

M8 slice 4. `pyproject.toml` says this dependency reproduces a crop byte for byte and validates
rotation; M7 established that such a claim belongs in a test against real output, not in prose next
to a version number. These are those tests.

Pure functions over bytes, so no database and no fixtures on disk: the PDF is built in memory,
because a binary fixture is a thing nobody reads and the point is to measure the library.

**M8 slice 5 added the image half**, because doc 08 `:983` lists images beside PDFs and
`SVC-PREVIEW-001` requires both to render. An image cannot hand its rotation to PDFium, so that path
uses `transpose` — a pixel permutation — where `rotate` would resample. The round-trip assertion is
what settles the difference; the documentation's word for it was not enough to pin a dependency on.

Covers: SVC-CROP-004, SVC-PREVIEW-001.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from app.exports.crop import (
    CROP_MEDIA_TYPE,
    PERMITTED_ROTATIONS,
    RENDER_SCALE,
    RENDERER_VERSION,
    WHOLE_PAGE,
    CropRefused,
    Rectangle,
    page_count,
    page_size,
    render_crop,
    render_page,
)
from PIL import Image

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


# ---------------------------------------------------------------------------
# M8 slice 5: the image path. doc 08 `:983` lists images beside PDFs.
# ---------------------------------------------------------------------------


def an_image() -> bytes:
    """A 40x20 PNG with a red block in the top-left corner.

    **Asymmetric in both axes on purpose.** A square with a centred mark rotates to something
    indistinguishable, so a test using one would pass with the direction reversed. The block
    is off-centre in both directions, which makes a wrong quarter turn visible.
    """

    picture = Image.new("RGB", (40, 20), (255, 255, 255))
    for x in range(10):
        for y in range(5):
            picture.putpixel((x, y), (255, 0, 0))
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return buffer.getvalue()


def test_an_image_is_one_page_and_is_not_upscaled() -> None:
    """Two claims that only apply to the image path.

    A photograph is its own raster, so `RENDER_SCALE` must not touch it: doubling a scan invents
    pixels the camera never recorded, and the operator would be drawing a rectangle on an
    interpolation. And an image has exactly one page — asserted because `page_count` feeds
    `bank_result_bundle_files.page_count`, which the review workspace uses to say "page 1 of N".
    """

    image = an_image()

    assert page_count(image) == 1
    assert page_size(image, 1) == (40, 20)
    assert page_size(image, 1, rotation=90) == (20, 40)

    rendered = render_page(image, page_number=1)
    assert (rendered.source_pixel_width, rendered.source_pixel_height) == (40, 20), (
        "the image was rescaled; a preview must show the pixels the scanner produced"
    )

    with pytest.raises(CropRefused):
        page_size(image, 2)


def test_an_image_renders_reproducibly_and_losslessly() -> None:
    """`SVC-PREVIEW-001` for the image half, and the reason it can claim byte equality.

    Rotation of an image cannot be handed to PDFium, so it is done with `transpose`, which permutes
    pixels, and never with `rotate`, which resamples them. The round trip is the assertion that
    settles it: four quarter turns must return the *exact* original pixels. A resampling rotate
    would blur the block's edges and fail this, while still passing a test that only compared two
    renders to each other.
    """

    image = an_image()
    original = Image.open(io.BytesIO(image)).convert("RGB")

    first = render_page(image, page_number=1)
    second = render_page(image, page_number=1)
    assert first.content == second.content
    assert first.media_type == CROP_MEDIA_TYPE

    turned = render_page(image, page_number=1, rotation_degrees=90)
    assert turned.content != first.content
    assert (turned.source_pixel_width, turned.source_pixel_height) == (20, 40)

    # A quarter clockwise, then three more, is the identity — if the turn is lossless.
    once = Image.open(io.BytesIO(turned.content))
    back = once.transpose(Image.Transpose.ROTATE_270).transpose(Image.Transpose.ROTATE_180)
    # `tobytes`, not `getdata`: the latter is deprecated for removal in Pillow 14, and raw bytes are
    # the stricter comparison anyway — every channel of every pixel, in order.
    assert back.tobytes() == original.tobytes(), (
        "four quarter turns did not return the original pixels, so the rotation resamples and no "
        "rotated preview is reproducible"
    )


def test_a_clockwise_turn_goes_clockwise() -> None:
    """The assertion no self-comparison can make.

    Pillow's `ROTATE_90` turns counter-clockwise and doc 08 `:985`'s control is clockwise, so the
    mapping is deliberately crossed in `_rotate_losslessly`. Every other rotation test here compares
    one render against another and would pass with the direction reversed — this one looks at where
    the red block actually landed.
    """

    turned = render_page(an_image(), page_number=1, rotation_degrees=90)
    picture = Image.open(io.BytesIO(turned.content))
    width, _ = picture.size

    assert picture.getpixel((width - 1, 0)) == (255, 0, 0), (
        "a clockwise quarter turn must move the top-left corner to the top-right"
    )
    assert picture.getpixel((0, 0)) == (255, 255, 255)


def test_bytes_that_are_neither_a_pdf_nor_an_image_are_refused() -> None:
    """A refusal, not a traceback.

    `mime_type_declared` is what the uploader said, so this path is reachable with any content at
    all. The message says what the renderer can accept rather than reporting a Pillow internal.
    """

    with pytest.raises(CropRefused):
        render_page(b"this is not a document", page_number=1)
    with pytest.raises(CropRefused):
        page_count(b"")


def test_a_whole_page_is_a_valid_rectangle() -> None:
    """The constant `render_page` is built on.

    If `WHOLE_PAGE` failed `Rectangle.validate()` every preview would be refused — and the check it
    has to survive is the boundary one: `x + width` is exactly 1, which the rule permits and an
    off-by-one reading of it would not.
    """

    WHOLE_PAGE.validate()
    assert WHOLE_PAGE.x + WHOLE_PAGE.width == Decimal("1")
    assert WHOLE_PAGE.y + WHOLE_PAGE.height == Decimal("1")

    # And a page render really is the crop of everything, not a separate path that happens to agree.
    document_page = render_page(TWO_PAGES, page_number=2)
    same_by_crop = render_crop(
        TWO_PAGES, page_number=2, rectangle=WHOLE_PAGE, rotation_degrees=0
    )
    assert document_page.content == same_by_crop.content
