"""Ten named synthetic bank fixtures. No real bank appears anywhere.

ADR-007's safe default is synthetic fixtures only, and the prohibition is not
squeamishness: a real bank's transfer limit or cutoff time sitting in source control
becomes production truth the moment somebody seeds it, and it drives real splitting
decisions on real money. So every profile here is invented, every IBAN is in a
reserved test range, and `test_bank_fixtures.py` asserts none of it looks real.

**The names are the contract.** `BANK_A_PROFILE_V1`, `BANK_A_MAPPING_V1`,
`BANK_A_MAPPING_V2`, `BANK_B_PROFILE_V1` and the rest are the identifiers the
evidence set refers to, so a test report and the plan can be read against each other.
`FIXTURE_SET_VERSION` is emitted into the run report by
`bank_fixture_report()` — a fixture set whose version nobody records is one where a
changed limit looks like a changed behaviour.

**Two mapping versions coexist inside one profile version**, and one is an import
mapping while the other is an export mapping at the same `template_version`. That
combination is the one a globally scoped unique would forbid, so it is a fixture
rather than only a test.

`BANK_A_MAPPING_INVALID` is included deliberately: a mapping whose field list
contains a value that must never reach SQL as an identifier. It exists so the
allowlist has something real to refuse.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import time
from typing import Any

# Bumped whenever any fixture's values change. Emitted into the run report.
FIXTURE_SET_VERSION = "bank-fixtures-1"

# `IR` plus 24 digits, all beginning `IR99` — not an allocated Iranian bank code, so
# no string here can collide with a real account. The test suite asserts the prefix.
_SYNTHETIC_IBAN_PREFIX = "IR99"


def synthetic_iban(suffix: str) -> str:
    """Build a shape-valid IBAN that cannot be a real account.

    Shape-valid matters: `bank_accounts` carries `~ '^IR[0-9]{24}$'`, so a fixture
    that failed the regex would exercise the rejection path instead of the accepted
    one.
    """

    if not suffix.isdigit() or len(suffix) > 22:
        raise ValueError(f"suffix must be at most 22 digits; got {suffix!r}")
    # `IR` + `99` + 22 digits = the 24 digits the constraint requires.
    return f"{_SYNTHETIC_IBAN_PREFIX}{suffix.rjust(22, '0')}"


@dataclass(frozen=True)
class ProfileFixture:
    name: str
    code: str
    display_name: str
    status: str
    purpose: str
    version_number: int = 1
    version_status: str = "active"
    default_transfer_limit_irr: int | None = None
    after_cutoff_transfer_limit_irr: int | None = None
    cutoff_time: time | None = None
    splitting_enabled: bool = False
    supports_description_field: bool = False
    required_fields: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AccountFixture:
    name: str
    profile: str
    display_name: str
    normalized_iban: str | None
    account_role: str
    status: str
    purpose: str


@dataclass(frozen=True)
class MappingFixture:
    name: str
    profile: str
    file_type: str
    template_version: int
    status: str
    mapping: dict[str, Any]
    purpose: str
    required_fields: dict[str, Any] = field(default_factory=dict)
    normalization_rules: dict[str, Any] = field(default_factory=dict)
    # True when the mapping deliberately contains a value that must never become a
    # SQL identifier. Used by the allowlist tests, never loaded as valid config.
    is_invalid: bool = False


PROFILES: tuple[ProfileFixture, ...] = (
    ProfileFixture(
        name="BANK_A_PROFILE_V1",
        code="synthetic_bank_a",
        display_name="بانک آزمایشی الف",
        status="active",
        purpose="the ordinary active profile most tests build on",
        splitting_enabled=True,
        supports_description_field=True,
        required_fields={"fields": ["beneficiary_name", "iban", "amount_irr"]},
    ),
    ProfileFixture(
        name="BANK_B_PROFILE_V1",
        code="synthetic_bank_b",
        display_name="بانک آزمایشی ب",
        status="active",
        purpose="a second bank, so nothing can pass by assuming one profile exists",
        supports_description_field=False,
        required_fields={"fields": ["beneficiary_name", "iban", "amount_irr"]},
    ),
    ProfileFixture(
        name="BANK_C_PROFILE_INACTIVE",
        code="synthetic_bank_c",
        display_name="بانک آزمایشی پ (غیرفعال)",
        status="inactive",
        version_status="retired",
        purpose="an inactive profile: selecting it must be refused later, not silently used",
    ),
    ProfileFixture(
        name="BANK_D_PROFILE_SPLIT_LIMITS",
        code="synthetic_bank_d",
        display_name="بانک آزمایشی ت (سقف تقسیم)",
        status="active",
        purpose="both transfer limits set, so splitting arithmetic has something to divide by",
        # Invented values. Round numbers on purpose, so nobody mistakes them for a
        # real bank's published limits.
        default_transfer_limit_irr=1_000_000_000,
        after_cutoff_transfer_limit_irr=500_000_000,
        splitting_enabled=True,
    ),
    ProfileFixture(
        name="BANK_E_PROFILE_CUTOFF_RULES",
        code="synthetic_bank_e",
        display_name="بانک آزمایشی ث (قواعد زمانی)",
        status="active",
        purpose="a cutoff time and time-shaped rules, evaluated in business time under ADR-006",
        cutoff_time=time(16, 0),
        after_cutoff_transfer_limit_irr=250_000_000,
        # Deliberately no holiday or working-day content: that ownership is Open and
        # encoding a guess here would become the calendar nobody approved.
        rules={"cutoff_applies_to": "same_business_day"},
    ),
)

ACCOUNTS: tuple[AccountFixture, ...] = (
    AccountFixture(
        name="SOURCE_ACCOUNT_A",
        profile="BANK_A_PROFILE_V1",
        display_name="حساب مبدأ الف",
        normalized_iban=synthetic_iban("1"),
        account_role="outgoing_source",
        status="active",
        purpose="the source outgoing batches draw on",
    ),
    AccountFixture(
        name="SOURCE_ACCOUNT_B",
        profile="BANK_B_PROFILE_V1",
        display_name="حساب مبدأ ب",
        normalized_iban=synthetic_iban("2"),
        account_role="both",
        status="active",
        purpose="a second source, and the only `both` role, so that value is exercised",
    ),
    AccountFixture(
        name="ACCOUNT_WITHOUT_IBAN",
        profile="BANK_A_PROFILE_V1",
        display_name="حساب بدون شبا",
        normalized_iban=None,
        account_role="incoming_destination",
        status="pending",
        purpose=(
            "the null-tolerant IBAN case: a centre account registered before its "
            "IBAN is known, which the beneficiaries' NOT NULL form would refuse"
        ),
    ),
)

MAPPINGS: tuple[MappingFixture, ...] = (
    MappingFixture(
        name="BANK_A_MAPPING_V1",
        profile="BANK_A_PROFILE_V1",
        file_type="outgoing_export",
        template_version=1,
        status="active",
        mapping={
            "columns": [
                {"header": "نام ذی‌نفع", "field": "beneficiary_name"},
                {"header": "شبا", "field": "iban"},
                {"header": "مبلغ", "field": "amount_irr"},
            ]
        },
        required_fields={"fields": ["beneficiary_name", "iban", "amount_irr"]},
        purpose="the export mapping at template_version 1",
    ),
    MappingFixture(
        name="BANK_A_MAPPING_V2",
        profile="BANK_A_PROFILE_V1",
        file_type="incoming_result",
        template_version=1,
        status="active",
        mapping={
            "columns": [
                {"header": "شبا", "field": "iban"},
                {"header": "وضعیت", "field": "result_status"},
                {"header": "شناسه پیگیری", "field": "reference_code"},
            ]
        },
        normalization_rules={"digits": "fold_persian_to_ascii"},
        purpose=(
            "an import mapping, also at template_version 1: the pair a globally "
            "scoped unique would forbid"
        ),
    ),
    MappingFixture(
        name="BANK_A_MAPPING_INVALID",
        profile="BANK_A_PROFILE_V1",
        file_type="outgoing_export",
        template_version=2,
        status="draft",
        mapping={
            "columns": [
                {"header": "نام", "field": "beneficiary_name"},
                # The reason this fixture exists. Never allowlisted, and the
                # identifier resolver must refuse it rather than quote it.
                {"header": "تزریق", "field": 'amount_irr"; DROP TABLE bank_mappings; --'},
            ]
        },
        purpose="a mapping value that must never reach SQL as an identifier",
        is_invalid=True,
    ),
)

PROFILES_BY_NAME: dict[str, ProfileFixture] = {p.name: p for p in PROFILES}
ACCOUNTS_BY_NAME: dict[str, AccountFixture] = {a.name: a for a in ACCOUNTS}
MAPPINGS_BY_NAME: dict[str, MappingFixture] = {m.name: m for m in MAPPINGS}

# The ten the evidence set names. Asserted as a set, so a rename is a visible
# failure rather than a fixture that quietly stops being referenced.
REQUIRED_FIXTURE_NAMES: frozenset[str] = frozenset(
    {
        "BANK_A_PROFILE_V1",
        "BANK_B_PROFILE_V1",
        "BANK_C_PROFILE_INACTIVE",
        "BANK_D_PROFILE_SPLIT_LIMITS",
        "BANK_E_PROFILE_CUTOFF_RULES",
        "SOURCE_ACCOUNT_A",
        "SOURCE_ACCOUNT_B",
        "BANK_A_MAPPING_V1",
        "BANK_A_MAPPING_V2",
        "BANK_A_MAPPING_INVALID",
    }
)

# Every identifier the synthetic mappings are permitted to reference. Supplied to
# `resolve_identifier` by tests; the real allowlist for a real export belongs to
# whichever milestone defines the export contract.
SYNTHETIC_ALLOWED_IDENTIFIERS: frozenset[str] = frozenset(
    {"beneficiary_name", "iban", "amount_irr", "result_status", "reference_code"}
)


def bank_fixture_report() -> dict[str, object]:
    """What the run report records: the version string and what it covers.

    Included in the evidence rather than left implicit, because "the bank fixtures
    passed" means nothing without knowing which fixtures those were.
    """

    return {
        "fixture_set_version": FIXTURE_SET_VERSION,
        "profiles": [p.name for p in PROFILES],
        "accounts": [a.name for a in ACCOUNTS],
        "mappings": [m.name for m in MAPPINGS],
        "manifest_digest": manifest_digest(),
    }


def manifest_digest() -> str:
    """A digest over every fixture's values, so a silent edit fails a pinned test."""

    digest = hashlib.sha256()
    digest.update(FIXTURE_SET_VERSION.encode("utf-8"))
    for name in sorted(REQUIRED_FIXTURE_NAMES):
        source: object = (
            PROFILES_BY_NAME.get(name) or ACCOUNTS_BY_NAME.get(name) or MAPPINGS_BY_NAME[name]
        )
        digest.update(repr(source).encode("utf-8"))
    return digest.hexdigest()
