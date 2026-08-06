"""The seeded flags and the model's list must be the same five.

`PHASE_1A_FLAGS` exists twice on purpose. The migration cannot import from `app`
at revision time without coupling a permanent schema record to a package that
keeps changing around it, so the five rows are written out in the revision; the
model carries them too, because that is where a reader looks for what the flags
are. Two copies drift, and the drift is silent — the seed is only executed on a
fresh database, so a divergence introduced today first appears months later on
whichever environment happens to be rebuilt.

This reads both and compares them. It also pins the values themselves, which is
the OPS-FLAG-001 assertion: everything AI, OCR, segmentation and bank-API is off,
and `break_glass` is not present in any spelling.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from app.db.models.configuration import PHASE_1A_FLAGS as MODEL_FLAGS

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "services"
    / "backend"
    / "alembic"
    / "versions"
    / "20260801_0010_configuration_and_retention.py"
)

# 04:1502-1506, transcribed once here so the test states the requirement rather
# than comparing two copies of the same possible mistake.
APPROVED_PHASE_1A_FLAGS: dict[str, bool] = {
    "manual_crop.enabled": True,
    "auto_segmentation.enabled": False,
    "ocr.enabled": False,
    "ai_matching.enabled": False,
    "bank_api.enabled": False,
}


def load_migration() -> Any:
    """Load the revision by path; Alembic versions are not importable modules."""

    spec = importlib.util.spec_from_file_location("configuration_seed", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_seeds_exactly_the_approved_five() -> None:
    """OPS-FLAG-001: the exact dotted keys, the exact values, and nothing else."""

    assert dict(load_migration().PHASE_1A_FLAGS) == APPROVED_PHASE_1A_FLAGS


def test_the_model_lists_exactly_the_approved_five() -> None:
    assert dict(MODEL_FLAGS) == APPROVED_PHASE_1A_FLAGS


def test_the_two_copies_have_not_drifted() -> None:
    """Compares them directly, so a change to one alone fails here.

    Distinct from the two tests above: those would both have to be edited to
    accommodate a divergence, but this one fails even if someone updates the
    approved dict and only one of the copies.
    """

    assert tuple(load_migration().PHASE_1A_FLAGS) == tuple(MODEL_FLAGS)


def test_only_manual_crop_is_enabled() -> None:
    """Phase 1A is manual. Every automated path ships off.

    A flag that arrives enabled turns a deployment into the moment an unreviewed
    OCR or matching path starts touching financial data.
    """

    enabled = sorted(key for key, value in MODEL_FLAGS if value)

    assert enabled == ["manual_crop.enabled"]


def test_no_break_glass_flag_is_seeded_in_any_spelling() -> None:
    """POL-005 prohibits the flag itself, not merely its enablement.

    Seeded false would still be a row that `feature_flag.update` can flip, and
    that permission's default grant is `technical_admin` — the role that must hold
    no financial authority. The database CHECK refuses the key outright; this
    catches the seed before it ever reaches the database.
    """

    for source in (MODEL_FLAGS, load_migration().PHASE_1A_FLAGS):
        assert not [key for key, _ in source if "break_glass" in key or "breakglass" in key]
