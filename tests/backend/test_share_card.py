"""The result card: reproducible, Persian, and carrying nothing the payload does not.

`FILE-PUBLICATION-001`. M9 slice 5B. No database — the renderer takes a dictionary and bytes and
returns bytes, so every property here is a property of the output.

**Reproduction is the obligation and it is not obvious.** A renderer can be correct and still be
irreproducible: Pillow will put a timestamp in a PNG chunk, its default resampling filter has
changed between releases, and a variable font's default instance is whatever the file says today.
Each of those is pinned in `app/exports/share_card.py`, and each has a test here rather than a
comment.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

import pytest
from app.exports.share_card import (
    FONT,
    RENDERER_VERSION,
    SHARE_MEDIA_TYPE,
    ShareCardRefused,
    render_share_card,
)
from PIL import Image, ImageFont

PAYLOAD = {
    "request_number": "PR-12ab34cd",
    "beneficiary_name": "علی رضایی",
    "beneficiary_iban_masked": "IR06*******0080",
    "amount_irr": "700000000",
    "paid_total_irr": "700000000",
    "attempts": [
        {
            "attempt_number": 1,
            "status": "paid",
            "amount_irr": "700000000",
            "bank_name": "بانک ملی",
            "bank_tracking_number": "820250830001",
            "bank_result_at": "2026-08-30T10:00:00+00:00",
            "failure_code": None,
        }
    ],
    "evidence_file_id": "b2f1c0de-0000-4000-8000-000000000001",
}


def a_crop(width: int = 240, height: int = 120) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_the_font_is_committed_beside_its_licence() -> None:
    """SIL OFL 1.1 requires the licence to travel with the font.

    `infra/scripts/refresh-webfont.sh` does the same for the two web copies and says why the font
    is vendored at all: Iran cannot reach the font hosts, and the image build has no registry.
    """

    assert FONT.exists(), (
        f"{FONT} is missing. It is a committed asset rather than an install step — a build that "
        "fetched a typeface would fail in the deployment country."
    )
    assert (FONT.parent / "Vazirmatn-OFL.txt").exists(), (
        "the font is committed without its licence, which SIL OFL 1.1 requires"
    )


def test_the_font_covers_persian_and_joins_its_letters() -> None:
    """Coverage and *shaping* are different claims, and only the second proves Raqm is working.

    A font with Persian glyphs but no shaping renders each letter in isolated form — legible to
    nobody who reads Persian. The discriminator is contextual joining: a connected pair is narrower
    than two isolated glyphs, because the joined forms overlap.

    This is the check that took three attempts. Comparing `direction="rtl"` against `"ltr"` proves
    nothing — for a pure-Persian string the bidi algorithm orders it the same either way — and a
    canvas narrower than the text proves less than nothing.
    """

    font = ImageFont.truetype(str(FONT), 28)
    isolated = font.getlength("پ", language="fa")
    joined = font.getlength("پپ", language="fa")

    assert isolated > 0, "the font has no glyph for a basic Persian letter"
    assert joined < 2 * isolated, (
        f"a connected pair measures {joined} against {2 * isolated} for two isolated glyphs, so "
        "the letters are not joining and Pillow is not shaping. Check "
        "`PIL.features.check('raqm')`."
    )


def test_two_renders_of_one_payload_are_byte_identical() -> None:
    """`FILE-PUBLICATION-001`, the whole of it.

    Rendered twice in one process, which is the floor. The stronger cross-process claim rests on
    the same pins — no timestamp, fixed geometry, one font instance — and there is nothing in the
    module that could differ between processes but not within one.
    """

    crop = a_crop()
    first = render_share_card(PAYLOAD, crop)
    second = render_share_card(PAYLOAD, crop)

    assert first == second, "the same publication rendered two different cards"
    assert first[:8] == b"\x89PNG\r\n\x1a\n", "the card is not a PNG"


def test_the_card_carries_no_timestamp() -> None:
    """Pillow will put the clock in a PNG chunk given the chance, and two renders would never
    match. Asserted over the bytes rather than trusting the save call's arguments."""

    card = render_share_card(PAYLOAD, a_crop())
    image = Image.open(io.BytesIO(card))
    assert "date:create" not in image.info
    assert "Creation Time" not in image.info
    assert image.info.get("tIME") is None


def test_a_different_payload_renders_a_different_card() -> None:
    """The control. If the renderer ignored its input, every test above would still pass."""

    crop = a_crop()
    other = {**PAYLOAD, "request_number": "PR-99999999"}
    assert render_share_card(PAYLOAD, crop) != render_share_card(other, crop)


def test_a_different_crop_renders_a_different_card() -> None:
    """The same control for the evidence half: a card that dropped the image would be stable and
    wrong, and `test_two_renders_of_one_payload_are_byte_identical` would not notice."""

    assert render_share_card(PAYLOAD, a_crop(240, 120)) != render_share_card(
        PAYLOAD, a_crop(200, 100)
    )


def test_a_publication_with_no_evidence_still_renders() -> None:
    """`share_file_id` is nullable and a publication may cite no evidence.

    The card is then the fields alone. Refusing here would make the absence of optional evidence
    fatal to a publication that is otherwise complete.
    """

    card = render_share_card(PAYLOAD, None)
    assert card[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(card) > 1000


def test_undecodable_evidence_is_refused_rather_than_skipped() -> None:
    """A card that quietly dropped unreadable evidence would look complete and show no proof."""

    with pytest.raises(ShareCardRefused, match="could not be decoded"):
        render_share_card(PAYLOAD, b"this is not an image")


def test_an_empty_payload_is_refused() -> None:
    with pytest.raises(ShareCardRefused):
        render_share_card({}, a_crop())


def test_the_renderer_version_names_both_things_that_can_change_a_pixel() -> None:
    """The provenance recorded on every derivation row.

    `crop.py` sets the precedent — it names the library *and* the pdfium build, because either
    changing can change a pixel. Here the two are Pillow and the font instance.
    """

    assert "pillow/" in RENDERER_VERSION
    assert "font/Vazirmatn-Regular-wght400" in RENDERER_VERSION, (
        "the renderer version does not pin the font instance. A variable font is many typefaces "
        "in one file, and a card rendered at a different weight is different bytes."
    )
    assert SHARE_MEDIA_TYPE == "image/png"


def test_the_module_reads_no_system_font() -> None:
    """A system-font lookup would make the output depend on the machine.

    On a plain Debian image the default Persian match is DejaVu Sans, which has no Arabic script
    at all — so a fallback renders boxes here and *different* boxes elsewhere. The font path is a
    module constant and there is no lookup to fall back from.

    **Read from the AST, not from the text.** The first version searched the source for the name
    of the font-matching tool, and matched this module's own docstring explaining why it does not
    use one — the same way a scan for an obligation id once matched the comment about that id.
    Prose written to justify a rule is not a breach of it.
    """

    module = (
        Path(__file__).resolve().parents[2]
        / "services"
        / "backend"
        / "app"
        / "exports"
        / "share_card.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))

    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = (
                callee.attr
                if isinstance(callee, ast.Attribute)
                else getattr(callee, "id", None)
            )
            if name:
                called.add(name)

    for lookup in ("findfont", "load_default", "findSystemFonts", "run", "check_output"):
        assert lookup not in called, (
            f"the renderer calls {lookup}(), so which typeface it uses depends on the machine "
            "rather than on the committed asset"
        )
    assert "truetype" in called, (
        "the renderer no longer loads a font file explicitly, so something else is choosing one"
    )
