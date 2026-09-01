#!/usr/bin/env bash
# Negative controls for M9 slice 5B — the share file.
#
# Controls 1 to 3 attack reproducibility, which is `FILE-PUBLICATION-001` and the reason this
# slice pins a font instance, a resampling filter and the PNG's metadata. Each of those is a
# default somebody would reasonably leave alone.
#
# Control 6 is the security one: it renders the card from the bundle instead of the crop, which is
# how every trader's results reach one trader through a file rather than through an API.
#
# Every touched file is copied and restored from the copy. Never `git checkout --`.

set -uo pipefail
cd "$(git rev-parse --show-toplevel)" || exit 1

CARD="services/backend/app/exports/share_card.py"
PUBLISH="services/backend/app/commands/payment_publication.py"
ROUTES="services/backend/app/api/v1/trader_publications.py"
BACKUP="$(mktemp -d)"

cp "$CARD" "$BACKUP/card.py"
cp "$PUBLISH" "$BACKUP/publish.py"
cp "$ROUTES" "$BACKUP/routes.py"

restore() {
  cp "$BACKUP/card.py" "$CARD"
  cp "$BACKUP/publish.py" "$PUBLISH"
  cp "$BACKUP/routes.py" "$ROUTES"
}
trap 'restore; rm -rf "$BACKUP"' EXIT

export NO_COLOR=1
: "${INTEGRATION_ADMIN_DATABASE_URL:?set it, or the live controls skip and read as NOT CAUGHT}"

PYTHON=services/backend/.venv/bin/python
UNIT=tests/backend/test_share_card.py
TRADER=tests/integration/test_trader_publications.py
PUBLICATIONS=tests/integration/test_payment_publications.py
OUT="$BACKUP/out.txt"

run() {
  local label="$1" expect="$2" target="$3"
  "$PYTHON" -m pytest -c services/backend/pyproject.toml "$target" -q > "$OUT" 2>&1

  if ! grep -qE '[0-9]+ (passed|failed)' "$OUT"; then
    printf '  INVALID RUN  %s\n' "$label"
    tail -4 "$OUT"
    restore
    return
  fi
  if grep -qE '[0-9]+ failed' "$OUT"; then
    printf '  CAUGHT   %-54s' "$label"
    if grep -q "$expect" "$OUT"; then
      echo "(on: $expect)"
    else
      echo "*** WRONG ASSERTION *** expected: $expect"
      grep -E '^FAILED' "$OUT" | head -4
    fi
  else
    printf '  NOT CAUGHT  %s\n' "$label"
  fi
  restore
}

echo "== M9 slice 5B negative controls =="

# 1. Let the PNG carry a timestamp. Two renders of one publication would then never match, and
#    `FILE-PUBLICATION-001` asks for exactly that to be impossible.
perl -0pi -e 's/    image\.save\(buffer, format="PNG", optimize=False, compress_level=6\)/    from PIL import PngImagePlugin\n    info = PngImagePlugin.PngInfo()\n    info.add_text("Creation Time", __import__("datetime").datetime.now().isoformat())\n    image.save(buffer, format="PNG", optimize=False, compress_level=6, pnginfo=info)/' "$CARD"
run "the card carries a timestamp" "test_the_card_carries_no_timestamp" "$UNIT"

# 2. Fall back to Pillow's bundled bitmap font. It has no Arabic script, so the card renders in a
#    typeface that depends on the machine rather than on the committed asset.
perl -0pi -e 's/    return ImageFont\.truetype\(str\(FONT\), size\)/    return ImageFont.load_default(size)/' "$CARD"
run "the renderer falls back to a system font" "test_the_module_reads_no_system_font" "$UNIT"

# 3. Drop the font instance from the provenance string. A card rendered at a different weight
#    would then be indistinguishable from one rendered at this weight.
perl -0pi -e 's/RENDERER_VERSION = f"share_card\/1 pillow\/\{PIL\.__version__\} font\/\{FONT_NAME\}"/RENDERER_VERSION = f"share_card\/1 pillow\/{PIL.__version__}"/' "$CARD"
run "the provenance drops the font instance" "test_the_renderer_version_names_both" "$UNIT"

# 4. Ignore the evidence entirely. The card would be stable, reproducible and missing the proof —
#    which the reproduction tests alone cannot see.
perl -0pi -e 's/^    if evidence:\r?\n        picture = _fitted\(evidence\)\r?\n        height \+= picture\.height \+ MARGIN\r?\n//m' "$CARD"
run "the card ignores the evidence" "test_a_different_crop_renders_a_different_card" "$UNIT"

# 5. Render around missing bytes instead of refusing. A card that silently dropped the proof looks
#    complete and is what a trader forwards to argue with.
#
#    The first version of this control was pointed at `test_the_bundle_never_enters_a_publication`
#    and went NOT CAUGHT — the wrong question, and chasing it found that **nothing tested this at
#    all**: the refusal existed with a comment explaining itself and no gate.
#    `test_a_crop_with_no_stored_bytes_refuses_the_publication` exists because of this control.
perl -0pi -e 's/    except FileBytesUnavailableError:/    except FileBytesUnavailableError:\n        evidence = None  # sabotage\n    if False:/' "$PUBLISH"
run "a missing crop renders a proofless card" "test_a_crop_with_no_stored_bytes_refuses" "$PUBLICATIONS"

# 6. Derive the card from the segment's *source* — the bank's mixed bundle — rather than its crop.
perl -0pi -e 's/    crop = uow\.session\.get\(FileObject, segment\.segment_file_id\)/    crop = uow.session.get(FileObject, segment.source_file_id)/' "$PUBLISH"
run "the card is rendered from the bundle" "test_the_publication_snapshot_reads_only_the_crop" "tests/backend/test_trader_surface_isolation.py"

# 7. Authorise the download by the file rather than by the publication's owner. A trader could
#    then fetch anybody's card by guessing a publication id.
perl -0pi -e 's/        require_owned\(request, request\.trader_id if request else None, actor\)/        pass/' "$ROUTES"
run "the download skips the ownership check" "test_another_trader_cannot_download_the_share_file" "$TRADER"

# 8. Remove **both** guards on a publication with no card. Removing only the `share_file_id is
#    None` half went NOT CAUGHT and correctly so: `session.get(FileObject, None)` returns `None`
#    and the second guard still answered 404. The property held for a reason the sabotage did not
#    touch — the third meaning — and two guards for one property is defence in depth rather than a
#    hole. This removes the pair, which is what the test is actually protecting.
perl -0pi -e 's/        if publication is None or publication\.share_file_id is None:/        if publication is None:/' "$ROUTES"
perl -0pi -e 's/        if card is None:  # pragma: no cover - the foreign key guarantees it\r?\n            uow\.rollback\(\)\r?\n            raise NotFoundError\(\)\r?\n//' "$ROUTES"
run "both guards on a missing card are gone" "test_a_publication_with_no_card_answers_404" "$TRADER"

echo "== done =="
