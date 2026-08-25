"""Cutting a rectangle out of a page, reproducibly. `08_Bank_File_and_Result_Processing.md` §15.

M8 slice 4. Pure rendering: this module opens bytes, produces bytes, and touches no database. The
same separation `app/exports/integrity.py` uses, and for the same reason — every property that
matters here is a property of the *output*, so it can be asserted without a session.

**Reproducibility is the whole point and it is a property of this file.**
`15_Agent_Implementation_Plan.md:1069` asks that "normalized coordinates reproduce the same crop
within approved tolerance". Measured before the renderer was pinned: re-rendering one rectangle at
the same version, scale and rotation is **byte-identical**, so there is no tolerance to approve —
Q-3. That holds only because everything variable is pinned here:

- `RENDER_SCALE` is a constant, not a parameter. A crop rendered at one scale and re-rendered at
  another would differ in every pixel while both claimed the same coordinates.
- The PNG is written with no timestamp. Pillow will happily put the clock in the chunk, and two
  renders of one rectangle would then never match.
- Rotation is applied by the renderer, not afterwards by rotating the raster. Rotating a bitmap
  resamples it; asking PDFium for a rotated page does not.

**`RENDERER_VERSION` is stored on every segment**, so a crop made today can be told apart from one
made after an upgrade. It is the library version and the pdfium build, because either changing can
change a pixel — and DOC-CONFLICT-057's reproduction claim is only as good as its ability to say
"this was made by that".
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import Decimal

import pypdfium2
from PIL import Image
from pypdfium2.version import PDFIUM_INFO, PYPDFIUM_INFO

# What a page is rasterised at. Fixed, and part of the provenance: at 2.0 a 300x400 point page
# becomes 600x800 pixels, which is enough for a person to read an amount off a bank receipt and
# small enough that a bundle of them is not gigabytes.
RENDER_SCALE = 2.0

# The same number, spelled for anything that records or hashes it. `app/core/hashing.py` refuses a
# float outright — "float cannot be hashed deterministically" — and it is right to: a float in a
# `parameters_hash` makes the digest depend on the platform's formatting, so two identical
# derivations could hash differently. The renderer wants a float and the record wants a string, so
# both spellings live here rather than being converted at each call site.
RENDER_SCALE_TEXT = "2.0"

# `receipt_segments.renderer_version`. Both halves, because either can change a pixel.
RENDERER_NAME = "pypdfium2"
RENDERER_VERSION = f"pypdfium2/{PYPDFIUM_INFO.version} pdfium/{PDFIUM_INFO.version}"

# The four angles `08_...Processing.md:985`'s preview can produce, matching the CHECK on the column.
PERMITTED_ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)

# PNG for the crop. Lossless, because a receipt that has been JPEG'd is evidence somebody can argue
# about, and the file is small enough that lossless costs nothing worth having.
CROP_MEDIA_TYPE = "image/png"


class CropRefused(Exception):
    """The rectangle or the page cannot produce a reproducible crop.

    Distinct from a storage or database failure: this is the caller having asked for something the
    renderer will not do, and §16.4's "validate normalized rectangle and rotation" is what it
    implements.
    """


@dataclass(frozen=True, slots=True)
class Rectangle:
    """A normalised rectangle, exactly as `receipt_segments` stores it.

    `Decimal`, never float: these four numbers have to reproduce a crop, and the column is
    `NUMERIC(10,6)`. A float would introduce a value the database never held.
    """

    x: Decimal
    y: Decimal
    width: Decimal
    height: Decimal

    def validate(self) -> None:
        """§12.4's CHECK, before the insert rather than after.

        The database refuses these too. Checking here means the caller gets a message naming the
        problem instead of a constraint name — and it means the renderer never wastes a page render
        on a rectangle that cannot be stored.
        """

        if self.width <= 0 or self.height <= 0:
            raise CropRefused("a crop needs a positive width and height")
        if self.x < 0 or self.y < 0:
            raise CropRefused("a crop cannot start outside the page")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise CropRefused(
                "a crop cannot extend past the page: coordinates are normalised to 0..1"
            )


@dataclass(frozen=True, slots=True)
class RenderedCrop:
    """The bytes and everything needed to make them again."""

    content: bytes
    media_type: str
    renderer_version: str
    rotation_degrees: int
    source_pixel_width: int
    source_pixel_height: int
    crop_pixel_width: int
    crop_pixel_height: int


def page_count(document: bytes) -> int:
    """How many pages, for `bank_result_bundle_files.page_count`."""

    return len(pypdfium2.PdfDocument(document))


def page_size(document: bytes, page_number: int, *, rotation: int = 0) -> tuple[int, int]:
    """The size one page would rasterise to, which is what a client normalises against.

    Returned in *pixels at `RENDER_SCALE`* rather than points, because that is what the operator's
    screen shows and what `client_source_dimensions` in `05_API_Specification.md:1773` is about.

    **Computed from the page's points, not by rendering it.** The first version rasterised the page
    and read `.size`, which meant the synchronous request path did the one expensive thing the
    asynchronous job exists to keep off it — a full page render, for two integers. Measured against
    real renders at both orientations and at an odd page size (301x399 points) before this was
    trusted, and `tests/backend/test_crop_renderer.py` re-asserts it: a computed size that
    drifted from the rendered one would reject every crop as drawn against the wrong raster.
    """

    pages = pypdfium2.PdfDocument(document)
    if page_number < 1 or page_number > len(pages):
        raise CropRefused(f"page {page_number} does not exist; the document has {len(pages)}")
    if rotation not in PERMITTED_ROTATIONS:
        raise CropRefused(f"rotation must be one of {PERMITTED_ROTATIONS}; received {rotation}")

    width_points, height_points = pages[page_number - 1].get_size()
    width = round(float(width_points) * RENDER_SCALE)
    height = round(float(height_points) * RENDER_SCALE)
    # A quarter turn swaps them, which is the whole reason `client_source_dimensions` has to be read
    # together with the angle rather than on its own.
    return (height, width) if rotation in (90, 270) else (width, height)


def render_crop(
    document: bytes,
    *,
    page_number: int,
    rectangle: Rectangle,
    rotation_degrees: int,
) -> RenderedCrop:
    """Cut `rectangle` out of `page_number` after rotating it, and return deterministic PNG bytes.

    **The rectangle is normalised against the rotated raster**, which is the entire reason
    DOC-CONFLICT-057 exists: an operator straightens a sideways scan and *then* draws, so the
    coordinates mean nothing without the angle they were drawn at. Rotating here before cropping is
    what makes the stored four numbers plus the stored angle reproduce what they saw.
    """

    if rotation_degrees not in PERMITTED_ROTATIONS:
        raise CropRefused(
            f"rotation must be one of {PERMITTED_ROTATIONS}; received {rotation_degrees}"
        )
    rectangle.validate()

    if page_number < 1:
        raise CropRefused("page numbers are 1-based")

    document_pages = pypdfium2.PdfDocument(document)
    if page_number > len(document_pages):
        raise CropRefused(
            f"page {page_number} does not exist; the document has {len(document_pages)}"
        )

    raster = _raster(document, page_number, rotation=rotation_degrees)
    width, height = raster.size

    left = round(float(rectangle.x) * width)
    top = round(float(rectangle.y) * height)
    right = round(float(rectangle.x + rectangle.width) * width)
    bottom = round(float(rectangle.y + rectangle.height) * height)

    # Rounding can collapse a very thin rectangle to nothing. Refused rather than stored: a
    # zero-pixel crop is a file that proves nothing and a row that claims evidence.
    if right <= left or bottom <= top:
        raise CropRefused(
            "the rectangle rounds to zero pixels at this render scale; select a larger region"
        )

    cropped = raster.crop((left, top, right, bottom))
    buffer = io.BytesIO()
    # No `optimize` and no metadata: both introduce variation between runs, and the whole claim of
    # this module is that two runs agree byte for byte.
    cropped.save(buffer, format="PNG", optimize=False)

    return RenderedCrop(
        content=buffer.getvalue(),
        media_type=CROP_MEDIA_TYPE,
        renderer_version=RENDERER_VERSION,
        rotation_degrees=rotation_degrees,
        source_pixel_width=width,
        source_pixel_height=height,
        crop_pixel_width=cropped.width,
        crop_pixel_height=cropped.height,
    )


def _raster(document: bytes, page_number: int, *, rotation: int) -> Image.Image:
    """One page as a bitmap.

    Rotation goes to the renderer rather than to the image afterwards. Rotating a raster resamples
    every pixel and would make a 90° crop differ from the same region rendered rotated — which is
    exactly the reproduction failure this module exists to prevent.
    """

    pages = pypdfium2.PdfDocument(document)
    page = pages[page_number - 1]
    bitmap = page.render(scale=RENDER_SCALE, rotation=rotation)

    # Annotated, not returned straight through. `pypdfium2` ships no `py.typed`, so everything it
    # hands back is `Any` — and this is the one line where that `Any` would escape into typed code.
    # Naming the type here keeps the untyped surface to this function instead of letting it spread
    # through every caller of `render_crop`.
    raster: Image.Image = bitmap.to_pil()
    return raster
