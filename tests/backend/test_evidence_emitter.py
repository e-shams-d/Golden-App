"""OPS-EVIDENCE-001: the artifact contains every field M2 can supply, and no bluff.

Four of the fifteen release-evidence fields can otherwise only be transcribed by
hand, which means a release candidate is accepted on evidence nobody can reproduce.
The emitter writes them instead.

The property under test is not "the JSON has keys". It is that **each field comes
from whoever actually knows it**, and that the two ways of faking the artifact are
both refused:

  - the revision must come from the running instance, so an unreachable instance
    produces **no artifact**, never one that quietly reads `alembic/versions/`
  - a field M2 cannot supply must be present and null **with its reason**, because an
    evidence set that silently lacks a field reads as complete

The unit tests here drive `build_artifact` against a stubbed instance response so the
shape and the refusals are pinned without a database.
`tests/integration/test_release_evidence_endpoint.py` covers the other half: that a
real instance reports the revision its own database records.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.emit_evidence import (
    UNFILLABLE_AT_M2,
    EvidenceError,
    ai_is_disabled,
    build_artifact,
    fetch_instance_evidence,
    fixture_versions,
    main,
)

MOMENT = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)

PHASE_1A_FLAGS = [
    {"flag_key": "ai_matching.enabled", "is_enabled": False},
    {"flag_key": "auto_segmentation.enabled", "is_enabled": False},
    {"flag_key": "bank_api.enabled", "is_enabled": False},
    {"flag_key": "manual_crop.enabled", "is_enabled": True},
    {"flag_key": "ocr.enabled", "is_enabled": False},
]


def instance_response(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "service": "gold-backend",
        "version": "0.1.0",
        "commit": "a" * 40,
        "environment": "ci",
        "schema_state": {
            "applied_revisions": ["20260801_0012"],
            "expected_revisions": ["20260801_0012"],
            "matches": True,
        },
        "feature_flags": PHASE_1A_FLAGS,
    }
    payload.update(overrides)
    return payload


class TestTheArtifactCarriesEveryFieldM2CanSupply:
    def test_the_schema_section_says_where_it_was_read_from(self) -> None:
        """The distinction the whole emitter exists for, recorded in the artifact.

        A reader months later cannot tell a revision read from a deployment from one
        read from a checkout unless the artifact says which it was.
        """

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert artifact["schema"]["applied_revisions"] == ["20260801_0012"]
        assert "not alembic/versions" in artifact["schema"]["read_from"]

    def test_each_field_is_attributed_to_its_source(self) -> None:
        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)
        sources = artifact["source_of_each_field"]

        assert "schema" in sources["instance"]
        assert "fixture_versions" in sources["repository"]
        assert "image_digests" in sources["build"]

    def test_the_test_data_set_version_names_both_fixture_sets_and_the_schema(self) -> None:
        """One string answering "which data was this run against".

        Two fixture sets and a schema revision, so the answer is not assembled by
        whoever reads the report.
        """

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)
        versions = fixture_versions()

        assert versions["file_fixtures"] in artifact["test_data_set_version"]
        assert versions["bank_fixtures"] in artifact["test_data_set_version"]
        assert "20260801_0012" in artifact["test_data_set_version"]

    def test_the_fixture_digests_are_recorded_not_just_the_version_strings(self) -> None:
        """A version string is a claim; a digest is a check.

        Both fixture sets pin their digests in their own tests, so recording the
        digest here lets an evidence reader confirm the run used the fixtures the
        version names.
        """

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert len(artifact["fixture_versions"]["file_fixtures_digest"]) == 64
        assert len(artifact["fixture_versions"]["bank_fixtures_digest"]) == 64

    def test_the_run_id_and_instant_are_recorded(self) -> None:
        artifact = build_artifact(instance_response(), run_id="run-77", moment=MOMENT)

        assert artifact["test_run_id"] == "run-77"
        assert artifact["emitted_at"] == MOMENT.isoformat()

    def test_image_digests_are_present_as_keys_even_when_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absent is a value. A missing key would read as "not applicable"."""

        for variable in (
            "BACKEND_IMAGE_DIGEST",
            "WORKER_IMAGE_DIGEST",
            "TRADER_PWA_IMAGE_DIGEST",
            "ADMIN_WEB_IMAGE_DIGEST",
            "NGINX_IMAGE_DIGEST",
        ):
            monkeypatch.delenv(variable, raising=False)

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert set(artifact["image_digests"]) == {
            "backend",
            "worker",
            "trader_pwa",
            "admin_web",
            "nginx",
        }
        assert all(value is None for value in artifact["image_digests"].values())

    def test_a_supplied_digest_is_carried_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BACKEND_IMAGE_DIGEST", "sha256:" + "b" * 64)

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert artifact["image_digests"]["backend"] == "sha256:" + "b" * 64


class TestWhatM2CannotSupplyIsStatedRatherThanOmitted:
    """An evidence set that silently lacks a field reads as complete."""

    @pytest.mark.parametrize("field", sorted(UNFILLABLE_AT_M2))
    def test_each_unfillable_field_is_present_with_a_reason(self, field: str) -> None:
        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert field in artifact["unfilled"]
        assert len(artifact["unfilled"][field]) > 40, "a reason, not a placeholder"

    def test_the_restore_drill_reason_names_the_open_decision(self) -> None:
        """ADR-004. Naming it means a reader can check whether the reason still holds."""

        assert "ADR-004" in UNFILLABLE_AT_M2["restore_drill"]

    def test_no_unfillable_field_is_also_reported_as_filled(self) -> None:
        """Guard the guard: a field in both places would satisfy either reader."""

        artifact = build_artifact(instance_response(), run_id="r1", moment=MOMENT)

        assert set(artifact) & set(UNFILLABLE_AT_M2) == set()


class TestTheAiDisabledClaim:
    def test_the_phase_1a_flag_set_reports_ai_disabled(self) -> None:
        assert ai_is_disabled(PHASE_1A_FLAGS) is True

    @pytest.mark.parametrize(
        "flag", ["ocr.enabled", "auto_segmentation.enabled", "ai_matching.enabled"]
    )
    def test_any_enabled_ai_flag_reports_ai_enabled(self, flag: str) -> None:
        """Checked by name, not by counting.

        A count of enabled flags would pass with `manual_crop` off and `ocr` on.
        """

        flags = [{**entry, "is_enabled": entry["flag_key"] == flag} for entry in PHASE_1A_FLAGS]

        assert ai_is_disabled(flags) is False

    def test_manual_crop_alone_being_enabled_is_not_ai(self) -> None:
        """Guard the guard: an over-broad check would call Phase 1A's only enabled
        path an AI path and fail every honest run."""

        flags = [
            {**entry, "is_enabled": entry["flag_key"] == "manual_crop.enabled"}
            for entry in PHASE_1A_FLAGS
        ]

        assert ai_is_disabled(flags) is True


class TestTheEmitterRefusesToBluff:
    def test_an_unreachable_instance_produces_no_artifact(self, tmp_path: Path) -> None:
        """The refusal that matters.

        A fallback to reading `alembic/versions/` would produce a plausible artifact
        describing a deployment nobody verified, which is worse than no artifact.
        """

        output = tmp_path / "evidence.json"
        exit_code = main(
            [
                "--base-url",
                # Loopback on a port nothing listens on: refused immediately. A
                # documentation-range address would be dropped instead, so the test
                # would spend its whole timeout proving the same thing.
                "http://127.0.0.1:9",
                "--operations-token",
                "t",
                "--output",
                str(output),
                "--timeout",
                "0.25",
            ]
        )

        assert exit_code == 1
        assert not output.exists(), "a partial artifact was written"

    def test_a_missing_token_fails_before_any_request(self, tmp_path: Path) -> None:
        output = tmp_path / "evidence.json"

        assert main(["--operations-token", "", "--output", str(output)]) == 2
        assert not output.exists()

    def test_the_fetch_error_names_the_repository_fallback_it_refuses(self) -> None:
        with pytest.raises(EvidenceError, match="does not fall back"):
            fetch_instance_evidence("http://127.0.0.1:9", "t", timeout=0.25)

    def test_a_schema_mismatch_is_recorded_and_fails_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The artifact records the mismatch **and** the run fails.

        Recording without failing would file the evidence and let the release
        proceed; failing without recording would lose why.
        """

        mismatched = instance_response(
            schema_state={
                "applied_revisions": ["20260801_0011"],
                "expected_revisions": ["20260801_0012"],
                "matches": False,
            }
        )
        monkeypatch.setattr(
            "scripts.emit_evidence.fetch_instance_evidence",
            lambda *args, **kwargs: mismatched,
        )
        output = tmp_path / "evidence.json"

        exit_code = main(["--operations-token", "t", "--output", str(output)])

        assert exit_code == 1
        written = json.loads(output.read_text(encoding="utf-8"))
        assert written["schema"]["matches"] is False
        assert written["schema"]["applied_revisions"] == ["20260801_0011"]

    def test_an_enabled_ai_flag_is_recorded_and_fails_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        enabled_ocr = instance_response(
            feature_flags=[
                {**entry, "is_enabled": entry["flag_key"] == "ocr.enabled"}
                for entry in PHASE_1A_FLAGS
            ]
        )
        monkeypatch.setattr(
            "scripts.emit_evidence.fetch_instance_evidence",
            lambda *args, **kwargs: enabled_ocr,
        )
        output = tmp_path / "evidence.json"

        exit_code = main(["--operations-token", "t", "--output", str(output)])

        assert exit_code == 1
        assert json.loads(output.read_text(encoding="utf-8"))["ai_disabled"] is False

    def test_a_clean_run_writes_the_artifact_and_succeeds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard the guard: every refusal above would pass on an emitter that always
        failed."""

        monkeypatch.setattr(
            "scripts.emit_evidence.fetch_instance_evidence",
            lambda *args, **kwargs: instance_response(),
        )
        output = tmp_path / "nested" / "evidence.json"

        assert main(["--operations-token", "t", "--output", str(output)]) == 0
        assert json.loads(output.read_text(encoding="utf-8"))["ai_disabled"] is True

    def test_the_artifact_is_utf8_with_unix_newlines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A published artifact whose bytes differ by platform cannot be hashed as
        evidence."""

        monkeypatch.setattr(
            "scripts.emit_evidence.fetch_instance_evidence",
            lambda *args, **kwargs: instance_response(),
        )
        output = tmp_path / "evidence.json"
        main(["--operations-token", "t", "--output", str(output)])

        raw = output.read_bytes()

        assert b"\r\n" not in raw
        assert raw.endswith(b"\n")
