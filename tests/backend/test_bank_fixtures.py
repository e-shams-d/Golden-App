"""The bank fixtures are synthetic, named, versioned, and provably not real.

ADR-007's safe default is synthetic fixtures only. The prohibition is not
squeamishness: a real bank's transfer limit or cutoff time in source control becomes
production truth the moment somebody seeds it, and it then drives real splitting
decisions on real money.

So this file checks three things that a reviewer cannot check by eye:

  - the ten named fixtures the evidence set refers to all exist
  - nothing in them looks like a real IBAN, phone number, or payment record
  - the digest is pinned, so a changed limit is a deliberate act rather than a
    line in a diff nobody read
"""

from __future__ import annotations

import re

import pytest
from bank_fixtures import (
    ACCOUNTS,
    ACCOUNTS_BY_NAME,
    FIXTURE_SET_VERSION,
    MAPPINGS,
    MAPPINGS_BY_NAME,
    PROFILES,
    PROFILES_BY_NAME,
    REQUIRED_FIXTURE_NAMES,
    AccountFixture,
    bank_fixture_report,
    manifest_digest,
    synthetic_iban,
)

PINNED_DIGEST = "0b11edda8ded634da20ef3a9758ca0a067df05e8e11b85d9a30ecfbdb002ba4f"

# Allocated Iranian bank codes occupy positions 3-5 of an IBAN. `99` is not one of
# them, so any fixture IBAN starting `IR99` cannot address a real account.
_RESERVED_TEST_PREFIX = "IR99"

# An Iranian mobile number. Present in no fixture; asserted, because a phone number
# is the field most likely to be pasted from something real while writing test data.
_IRANIAN_MOBILE = re.compile(r"(\+98|0)9\d{9}")


def test_the_ten_named_fixtures_all_exist() -> None:
    """The names are the contract between the plan and the evidence set."""

    present = set(PROFILES_BY_NAME) | set(ACCOUNTS_BY_NAME) | set(MAPPINGS_BY_NAME)

    assert present >= REQUIRED_FIXTURE_NAMES, (
        f"missing named fixtures: {sorted(REQUIRED_FIXTURE_NAMES - present)}"
    )
    assert len(REQUIRED_FIXTURE_NAMES) == 10


def test_the_run_report_carries_the_version_string() -> None:
    """A fixture set whose version nobody records is one where a changed limit looks
    like a changed behaviour."""

    report = bank_fixture_report()

    assert report["fixture_set_version"] == FIXTURE_SET_VERSION
    assert report["manifest_digest"] == manifest_digest()
    for key in ("profiles", "accounts", "mappings"):
        assert report[key], f"{key} is empty in the run report"


def test_the_manifest_digest_is_pinned() -> None:
    computed = manifest_digest()

    assert computed == PINNED_DIGEST, (
        f"the bank fixture set changed. Version is {FIXTURE_SET_VERSION!r}; bump it "
        f"and set PINNED_DIGEST to:\n{computed}"
    )


class TestNothingLooksReal:
    """BANK-FIXTURE-001's second half, and the one worth automating."""

    @pytest.mark.parametrize("fixture", ACCOUNTS, ids=lambda a: a.name)
    def test_every_iban_is_in_the_reserved_test_range(self, fixture: AccountFixture) -> None:
        iban = fixture.normalized_iban
        if iban is None:
            return

        assert iban.startswith(_RESERVED_TEST_PREFIX), (
            f"{iban} is not in the reserved test range, so it may address a real account"
        )
        assert re.fullmatch(r"IR[0-9]{24}", iban), (
            f"{iban} does not match the database constraint, so this fixture would "
            "exercise the rejection path instead of the accepted one"
        )

    def test_the_iban_builder_produces_a_constraint_valid_value(self) -> None:
        built = synthetic_iban("7")

        assert re.fullmatch(r"IR[0-9]{24}", built)
        assert built.startswith(_RESERVED_TEST_PREFIX)

    def test_the_iban_builder_refuses_a_value_that_would_not_fit(self) -> None:
        with pytest.raises(ValueError):
            synthetic_iban("1" * 23)

    def test_no_fixture_contains_an_iranian_mobile_number(self) -> None:
        """The field most likely to be pasted from something real."""

        for fixture in (*PROFILES, *ACCOUNTS, *MAPPINGS):
            assert not _IRANIAN_MOBILE.search(repr(fixture)), (
                f"{fixture.name} contains something shaped like a real phone number"
            )

    def test_every_profile_code_announces_itself_as_synthetic(self) -> None:
        """So a code that reached production could not be mistaken for a real bank."""

        for profile in PROFILES:
            assert profile.code.startswith("synthetic_"), (
                f"{profile.name} has code {profile.code!r}, which does not say it is synthetic"
            )

    def test_the_limits_are_round_invented_numbers(self) -> None:
        """A published bank limit is rarely a round billion. Keeping the fixtures
        obviously invented is what stops one being quoted as fact."""

        for profile in PROFILES:
            for limit in (
                profile.default_transfer_limit_irr,
                profile.after_cutoff_transfer_limit_irr,
            ):
                if limit is not None:
                    assert limit % 1_000_000 == 0, f"{profile.name} has an oddly specific limit"


class TestTheCombinationsThatMatter:
    def test_two_mappings_share_a_template_version_under_one_profile(self) -> None:
        """The pair a globally scoped unique would forbid, held as a fixture rather
        than only asserted in a test."""

        first = MAPPINGS_BY_NAME["BANK_A_MAPPING_V1"]
        second = MAPPINGS_BY_NAME["BANK_A_MAPPING_V2"]

        assert first.profile == second.profile
        assert first.template_version == second.template_version == 1
        assert first.file_type != second.file_type

    def test_an_inactive_profile_exists(self) -> None:
        assert PROFILES_BY_NAME["BANK_C_PROFILE_INACTIVE"].status == "inactive"

    def test_a_profile_with_both_split_limits_exists(self) -> None:
        profile = PROFILES_BY_NAME["BANK_D_PROFILE_SPLIT_LIMITS"]

        assert profile.default_transfer_limit_irr is not None
        assert profile.after_cutoff_transfer_limit_irr is not None
        assert profile.splitting_enabled is True

    def test_a_profile_with_a_cutoff_time_exists(self) -> None:
        profile = PROFILES_BY_NAME["BANK_E_PROFILE_CUTOFF_RULES"]

        assert profile.cutoff_time is not None
        # No timezone on the value: a cutoff is a wall clock read in business time
        # under ADR-006, not an instant.
        assert profile.cutoff_time.tzinfo is None

    def test_no_fixture_encodes_a_holiday_or_working_day_calendar(self) -> None:
        """Calendar ownership is Open. A guess encoded in a fixture becomes the
        calendar nobody approved, because fixtures get copied into real config."""

        for profile in PROFILES:
            rendered = repr(profile.rules).lower()
            for forbidden in ("holiday", "weekend", "working_day", "jalali", "shamsi"):
                assert forbidden not in rendered, (
                    f"{profile.name} encodes calendar content ({forbidden}) that no "
                    "approved decision covers"
                )

    def test_an_account_without_an_iban_exists(self) -> None:
        """The null-tolerant case. Without this fixture the constraint's tolerance is
        asserted only by a hand-written NULL in one test."""

        assert ACCOUNTS_BY_NAME["ACCOUNT_WITHOUT_IBAN"].normalized_iban is None

    def test_exactly_one_account_holds_the_both_role(self) -> None:
        both = [a.name for a in ACCOUNTS if a.account_role == "both"]

        assert both == ["SOURCE_ACCOUNT_B"]
