"""The result card a trader downloads. `08_Bank_File_and_Result_Processing.md` §19.4.

M9 slice 5B. Pure rendering: this module takes a dictionary and some bytes, returns bytes, and
touches no database — the same separation `app/exports/crop.py` and `app/exports/integrity.py` use,
and for the same reason. Every property that matters here is a property of the *output*, so it can
be asserted without a session.

**§19.4 bounds the content in one sentence**: "Phase 1A may generate an image or PDF-like result
card containing structured fields. It must not include unrelated data or raw mixed evidence." The
card is rendered from a publication's `summary_payload` and nothing else, which is already the
masked, hashed, privacy-reviewed snapshot — so the bound is satisfied by where the input comes from
rather than by filtering here.

**Reproducibility is a property of this file, exactly as it is for the crop.**
`FILE-PUBLICATION-001` asks that the same publication renders byte-for-byte the same card, and that
holds only because everything variable is pinned:

- `FONT` is a **committed, single-instance** file. Vazirmatn is a variable font; the vendored copy
  is instanced at `wght=400`, so "the font" means one typeface rather than whatever the default
  instance becomes after an upgrade. `infra/scripts/refresh-webfont.sh` argues the vendoring at
  length — Iran cannot reach the font hosts and the image build has no registry — and this is the
  backend's copy of that decision.
- Sizes and the canvas are constants, not parameters. A card rendered at one width and re-rendered
  at another would differ in every pixel while both claimed the same publication.
- The PNG is written with no timestamp. Pillow will otherwise put the clock in a chunk and two
  renders of one publication would never match.
- Nothing is read from the system font stack. `fc-match ":lang=fa"` on a plain Debian image returns
  DejaVu Sans, which has **no Arabic script at all** — a fallback would render boxes here and
  different boxes on a different base image.

**Persian is shaped by Pillow, not by a new dependency.** Pillow is built with Raqm
(`features.check("raqm")`), which applies the Unicode bidi algorithm and Arabic contextual joining.
Measured rather than assumed: `getlength("پپ")` is 34.7px against 49.0px for two isolated glyphs,
so the letters really do connect. Nothing was added to the frozen dependency graph.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import PIL
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent / "fonts"
FONT = FONTS / "Vazirmatn-Regular.ttf"

# The typeface as provenance. Both halves, because either can change a pixel — the same shape as
# `crop.py`'s `RENDERER_VERSION`, which names the library and the pdfium build.
FONT_NAME = "Vazirmatn-Regular-wght400"
RENDERER_NAME = "share_card"
RENDERER_VERSION = f"share_card/1 pillow/{PIL.__version__} font/{FONT_NAME}"

# PNG, and lossless for the reason the crop is: a receipt a trader forwards to their accountant is
# a document somebody may argue about, and the file is small enough that lossless costs nothing.
SHARE_MEDIA_TYPE = "image/png"

# Fixed geometry. Every one of these is part of the digest by being unchangeable at call time.
CARD_WIDTH = 900
MARGIN = 40
LINE_HEIGHT = 46
TITLE_SIZE = 30
LABEL_SIZE = 22
EVIDENCE_WIDTH = CARD_WIDTH - (2 * MARGIN)
EVIDENCE_MAX_HEIGHT = 420

BACKGROUND = "white"
INK = "black"
RULE = "#c8c8c8"

# Right-aligned, because the card is Persian. The text anchor is the right edge of the content box.
TEXT_ANCHOR = "ra"

# What the card shows, in order, as (Persian label, payload key). **Read from `summary_payload`
# only** — a key absent from the payload renders as an em dash rather than reaching into a model,
# which is what keeps §19.4's "must not include unrelated data" true by construction.
FIELDS: tuple[tuple[str, str], ...] = (
    ("شماره درخواست", "request_number"),
    ("ذی‌نفع", "beneficiary_name"),
    ("شماره شبا", "beneficiary_iban_masked"),
    ("مبلغ درخواست", "amount_irr"),
    ("مبلغ پرداخت‌شده", "paid_total_irr"),
)

TITLE = "رسید نتیجه پرداخت"
ATTEMPT_HEADING = "تراکنش‌های بانکی"
EMPTY = "—"


class ShareCardRefused(Exception):
    """The card cannot be rendered from what was supplied."""


def _font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT.exists():  # pragma: no cover - the asset is committed
        raise ShareCardRefused(
            f"the share-card font is missing at {FONT}. It is a committed asset, not an install "
            "step — see `infra/scripts/refresh-webfont.sh` for why this platform vendors its "
            "typeface rather than fetching one."
        )
    return ImageFont.truetype(str(FONT), size)


def _write(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, size: int) -> None:
    """One line of Persian, right-anchored and shaped.

    `direction="rtl"` and `language="fa"` are passed on every call rather than set once, because
    Pillow takes them per draw and a line that forgot them would render in visual order — which
    looks almost right and is not.
    """

    draw.text(
        (x, y),
        text,
        font=_font(size),
        fill=INK,
        anchor=TEXT_ANCHOR,
        direction="rtl",
        language="fa",
    )


def _grouped(amount: str) -> str:
    """`700000000` -> `700,000,000`. Digits stay ASCII.

    Persian digits would read more naturally and are **not** used: the payload's amounts are
    decimal strings that a reader may need to compare against a bank statement, and
    `app/core/hashing.py` folds Persian digits to ASCII precisely because the two spellings are the
    same number to a person and different bytes to a machine. A card is the wrong place to
    introduce that ambiguity.
    """

    try:
        return f"{int(amount):,}"
    except (TypeError, ValueError):
        return str(amount)


def render_share_card(payload: dict[str, Any], evidence: bytes | None = None) -> bytes:
    """One publication's `summary_payload` as a PNG. Deterministic for identical inputs.

    `evidence` is the crop the publication cites, already rendered by M8 and already the
    trader-safe file — §19.4's "must not include raw mixed evidence" is satisfied upstream, by
    `payment_publication._safe_evidence_file_id` refusing anything but a crop.
    """

    if not isinstance(payload, dict) or not payload:
        raise ShareCardRefused("a share card needs a publication payload to render")

    attempts = payload.get("attempts") or []
    rows = len(FIELDS) + 2 + max(len(attempts), 1)
    height = MARGIN * 2 + int(TITLE_SIZE * 1.8) + rows * LINE_HEIGHT

    picture = None
    if evidence:
        picture = _fitted(evidence)
        height += picture.height + MARGIN

    image = Image.new("RGB", (CARD_WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    right = CARD_WIDTH - MARGIN
    y = MARGIN

    _write(draw, right, y, TITLE, TITLE_SIZE)
    y += int(TITLE_SIZE * 1.8)
    draw.line([(MARGIN, y), (right, y)], fill=RULE, width=1)
    y += LINE_HEIGHT // 2

    for label, key in FIELDS:
        value = payload.get(key)
        if key.endswith("_irr") and value is not None:
            value = _grouped(str(value))
        _write(draw, right, y, f"{label}:  {value if value else EMPTY}", LABEL_SIZE)
        y += LINE_HEIGHT

    y += LINE_HEIGHT // 2
    _write(draw, right, y, ATTEMPT_HEADING, LABEL_SIZE)
    y += LINE_HEIGHT

    if not attempts:
        _write(draw, right, y, EMPTY, LABEL_SIZE)
        y += LINE_HEIGHT
    for attempt in attempts:
        tracking = attempt.get("bank_tracking_number") or EMPTY
        bank = attempt.get("bank_name") or EMPTY
        amount = _grouped(str(attempt.get("amount_irr", "")))
        _write(draw, right, y, f"{bank}  •  {tracking}  •  {amount}", LABEL_SIZE)
        y += LINE_HEIGHT

    if picture is not None:
        y += MARGIN // 2
        # Left-aligned inside the margin: an image has no reading direction, and centring it would
        # make the card's width part of its layout in a way a different field length could shift.
        image.paste(picture, (MARGIN, y))

    buffer = io.BytesIO()
    # `optimize=False` and no `pnginfo`: both would let Pillow's defaults, or the clock, into the
    # bytes. The file is a few tens of kilobytes either way.
    image.save(buffer, format="PNG", optimize=False, compress_level=6)
    return buffer.getvalue()


def _fitted(evidence: bytes) -> Image.Image:
    """The evidence crop, scaled to the card's width and never up.

    **Never enlarged**, which is `crop.py`'s rule about evidence pixels arriving here: scaling a
    receipt up invents detail that the bank's document did not contain, and a trader reading an
    amount off it would be reading an interpolation. Shrinking discards, which is honest.
    """

    try:
        opened = Image.open(io.BytesIO(evidence))
        opened.load()
    except Exception as error:
        raise ShareCardRefused(
            f"the cited evidence could not be decoded as an image: {type(error).__name__}"
        ) from error

    picture = opened.convert("RGB")
    if picture.width <= EVIDENCE_WIDTH and picture.height <= EVIDENCE_MAX_HEIGHT:
        return picture

    ratio = min(EVIDENCE_WIDTH / picture.width, EVIDENCE_MAX_HEIGHT / picture.height)
    size = (max(1, int(picture.width * ratio)), max(1, int(picture.height * ratio)))
    # `LANCZOS` named explicitly: Pillow's default resampling has changed between releases, and a
    # default here would make the card's bytes depend on the library version rather than on the
    # publication. The version is in `RENDERER_VERSION` either way, but a pinned filter means an
    # upgrade does not silently invalidate every stored card.
    return picture.resize(size, Image.Resampling.LANCZOS)
