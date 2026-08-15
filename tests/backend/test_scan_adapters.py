"""The scan policy: two adapters, and no third.

Covers: FILE-SCAN-002, FILE-SCAN-004, FILE-LIFE-002.

FILE-SCAN-001 and -003 are in `tests/integration/test_scan_policy.py`: one is about what a
real upload lands in, the other about the database refusing `available` independently of
this code, and neither can be proved without a database.

Named `test_scan_adapters` because the integration file is already `test_scan_policy`, and
basenames must be unique across the two suites. That rule was written one slice ago, after
a collision stopped CI from collecting anything at all — and it caught this file on its
first run, which is the difference between a convention and a gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.files.scanning import (
    POLICY_DEVELOPMENT_BYPASS,
    POLICY_NAMES,
    POLICY_NONE,
    DevelopmentScanBypass,
    NoScannerConfigured,
    build_scan_policy,
)
from app.files.states import SCAN_CLEAN, SCAN_PENDING, SCAN_STATUSES

APP = Path(__file__).resolve().parents[2] / "services" / "backend" / "app"


def test_the_production_default_reports_nothing_as_scanned() -> None:
    """The honest answer when nothing scans, rather than a stub that pretends."""

    result = NoScannerConfigured().scan(storage_key="incoming_payment_receipt/x/y")
    assert result.status == SCAN_PENDING
    assert not result.permits_availability


def test_the_development_bypass_refuses_to_exist_in_production() -> None:
    """FILE-SCAN-002.

    Not a warning and not a log line: construction fails, so the application does not
    start rather than starting with scanning silently off. The same pattern
    `app/cli/seed_demo.py` uses, for the same reason.
    """

    with pytest.raises(ValueError, match="cannot be used in production"):
        DevelopmentScanBypass(app_env="production")

    for environment in ("local", "test", "staging"):
        assert DevelopmentScanBypass(app_env=environment).scan(storage_key="k").status == SCAN_CLEAN


def test_the_factory_refuses_a_production_bypass_too() -> None:
    """The refusal has to survive the indirection, because configuration goes through the
    factory and nothing constructs the adapter directly."""

    with pytest.raises(ValueError, match="cannot be used in production"):
        build_scan_policy(policy_name=POLICY_DEVELOPMENT_BYPASS, app_env="production")


def test_an_unknown_policy_name_is_refused_rather_than_defaulted() -> None:
    """Not even to the safe adapter.

    A typo that silently selects a policy is a deployment not running the policy it was
    configured with — and if the fallback were the permissive one, that is a scanner
    switched off by a spelling mistake.
    """

    for unknown in ("", "clamav", "None", "development-bypass"):
        with pytest.raises(ValueError, match="unknown scan policy"):
            build_scan_policy(policy_name=unknown, app_env="test")


def test_the_only_two_policies_are_the_two_that_are_named() -> None:
    """FILE-LIFE-002's neighbour: the set is closed, and closing it is what makes the
    absence of a third adapter a decision rather than an omission."""

    assert POLICY_NAMES == (POLICY_NONE, POLICY_DEVELOPMENT_BYPASS)
    assert isinstance(
        build_scan_policy(policy_name=POLICY_NONE, app_env="test"), NoScannerConfigured
    )
    assert isinstance(
        build_scan_policy(policy_name=POLICY_DEVELOPMENT_BYPASS, app_env="test"),
        DevelopmentScanBypass,
    )


def test_no_adapter_can_report_availability_without_a_clean_scan() -> None:
    """`permits_availability` is derived from the status, never set beside it.

    An adapter able to report "not clean, but available anyway" would be the whole hole
    this module exists to close, so the property is computed and this asserts it across
    every status the application knows.
    """

    from app.files.scanning import ScanResult

    for status in SCAN_STATUSES:
        assert ScanResult(status).permits_availability is (status == SCAN_CLEAN)


def test_no_scan_adapter_produces_the_reserved_skip_outcome() -> None:
    """FILE-SCAN-004.

    `test_reserved_scan_status.py` already refuses the literal anywhere in runtime code
    outside the model that declares it. This adds the behavioural half: the adapters that
    exist return only `pending` and `clean`, so even a future reader who found the value
    would find no adapter reaching for it.

    Note what is *not* claimed. The value is not refused by a database constraint, and
    that is deliberate — a scanner that genuinely skipped a file has stated a fact, and a
    schema that could not record it would force the caller to write something else. What
    is impossible is the consequence, and `available_requires_clean_scan` handles that.
    """

    produced = {
        NoScannerConfigured().scan(storage_key="k").status,
        DevelopmentScanBypass(app_env="test").scan(storage_key="k").status,
    }
    assert produced == {SCAN_PENDING, SCAN_CLEAN}


def test_the_scanning_module_names_no_reserved_value() -> None:
    """Guard the guard, from this side.

    The repository-wide gate excludes exactly one declaring module. This asserts that the
    scanning module — the one most likely to reach for the value, since it is the module
    about scan outcomes — is not quietly added to that exclusion later.
    """

    source = (APP / "files" / "scanning.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not any("skipped_by" in value for value in literals)
