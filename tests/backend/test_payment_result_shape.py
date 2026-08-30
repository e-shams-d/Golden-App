"""What a confirmation cannot say, and what it cannot write.

`SVC-CONFIRM-003` and part of `SEC-CONFIRM-001`. No database, so neither can become a skip.

**"Amount is exact" is enforced by an absence, and an absence is exactly what a behavioural test
cannot check.** §17 `:1131` requires the confirmed amount to be exact; document 05's request body
carries no amount at all. So there is no number a client could send that disagrees with the
attempt's own `amount_irr` — and the assertion is over the request models, not over a value.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from app.api.v1.payment_attempts import ConfirmFailedRequest, ConfirmPaidRequest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "backend"
MIGRATION = (
    BACKEND / "alembic" / "versions" / "20260830_0030_attempt_result_grant.py"
)
COMMAND = BACKEND / "app" / "commands" / "payment_result.py"

# Anything that could carry money into a confirmation. Deliberately broad: a false positive costs
# a rename and a false negative costs the rule.
MONETARY_HINTS = ("amount", "irr", "toman", "rial", "total", "sum", "value")

# §11.3's snapshots and lineage. A confirmation records what the bank did; it must not be able to
# restate what was sent.
MUST_STAY_UNWRITABLE = (
    "amount_irr",
    "beneficiary_name_snapshot",
    "beneficiary_iban_snapshot",
    "beneficiary_national_id_snapshot",
    "bank_profile_version_id",
    "payment_request_id",
    "payment_request_revision_id",
    "attempt_number",
    "attempt_type",
    "retry_of_attempt_id",
    "supersedes_attempt_id",
    "split_rule_snapshot",
)


@pytest.mark.parametrize("model", [ConfirmPaidRequest, ConfirmFailedRequest])
def test_no_confirmation_body_accepts_an_amount(model: type) -> None:
    """`SVC-CONFIRM-003`. The field does not exist, so it cannot disagree.

    Checked over the model's own fields rather than by posting a body, because a request that
    *rejects* an amount and a request that has no such field are different guarantees — and only
    the second one survives somebody adding `extra="allow"`.
    """

    offenders = [
        name
        for name in model.model_fields
        if any(hint in name.lower() for hint in MONETARY_HINTS)
    ]
    assert offenders == [], (
        f"{model.__name__} accepts {offenders}. §17 `:1131` requires the confirmed amount to be "
        "exact, and the attempt already knows it: a client-supplied figure is a number that can "
        "disagree with the one that was sent to a bank."
    )


@pytest.mark.parametrize("model", [ConfirmPaidRequest, ConfirmFailedRequest])
def test_both_bodies_forbid_unknown_fields(model: type) -> None:
    """The control on the test above.

    Without `extra="forbid"` an amount could arrive in a body that does not declare one, and the
    field-name scan would report a clean model while the value was there to be read.
    """

    assert model.model_config.get("extra") == "forbid", model.__name__


def test_the_grant_names_only_result_columns() -> None:
    """`SEC-CONFIRM-001`, the half that can be read from source.

    The live half — that the runtime role really cannot UPDATE the snapshots — is
    `tests/integration/test_payment_results.py`, because a grant is a database fact and a
    migration is only a claim about one.
    """

    text = MIGRATION.read_text(encoding="utf-8")
    granted = re.search(r"GRANTED_COLUMNS = \((.*?)\)", text, re.S)
    assert granted is not None, "the grant list has moved; this test reads nothing"

    columns = {value.strip().strip('",') for value in granted.group(1).split() if value.strip()}
    columns = {value for value in columns if value and not value.startswith("#")}
    assert columns, "no columns parsed from GRANTED_COLUMNS"

    leaked = sorted(columns & set(MUST_STAY_UNWRITABLE))
    assert leaked == [], (
        f"the migration grants UPDATE on {leaked}. A confirmation records what the bank did and "
        "must not be able to restate what was sent."
    )


def test_the_recalculation_has_no_branch_for_a_case_it_never_sees() -> None:
    """The sixteenth mechanism-with-no-caller, prevented rather than found later.

    `_recalculate` is reached only after the overpayment check has already raised, so a
    `paid > requested` branch inside it could never execute. This asserts it is not there — the
    same reasoning that deleted G-5's export guard, applied before the code shipped rather than
    after.
    """

    tree = ast.parse(COMMAND.read_text(encoding="utf-8"))
    recalculate = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_recalculate"
        ),
        None,
    )
    assert recalculate is not None, "_recalculate has been renamed; this test reads nothing"

    comparisons = [
        node
        for node in ast.walk(recalculate)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, ast.Gt | ast.GtE) for op in node.ops)
    ]
    assert comparisons == [], (
        "`_recalculate` contains a greater-than comparison, which suggests a branch for the "
        "overpayment case. That case raises before this function is called, so such a branch "
        "could never run."
    )
