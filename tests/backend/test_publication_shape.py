"""What a publication cannot say, what its hash cannot see, and what its table cannot become.

`SVC-PUBLICATION-002`, `SVC-PUBLICATION-003` and `SEC-PUBLICATION-001`. No database, so none of
them can turn into a skip on a machine without PostgreSQL.

**Two of the three properties here are absences**, and an absence is exactly what a behavioural
test cannot check:

- no financial field in either request body, so a client cannot submit a summary value;
- no `published_at`, `publication_version` or actor in the hashed payload, so
  `UNIQUE(payment_request_id, content_hash)` still has something it can refuse;
- no `UPDATE` grant in the migration, so §11.9's word "immutable" is enforced rather than asserted.

The third is a scan over the trader surface rather than over this slice's own module, because §17
`:1185` asks that the full bundle never reaches trader APIs *or files* — and the thing somebody
adds under pressure gets added wherever it is convenient.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from app.api.v1.payment_publications import PreviewRequest, PublishRequest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "services" / "backend"
MIGRATION = (
    BACKEND / "alembic" / "versions" / "20260831_0031_payment_result_publications.py"
)
COMMAND = BACKEND / "app" / "commands" / "payment_publication.py"
ROUTER = BACKEND / "app" / "api" / "v1" / "payment_publications.py"

# Anything that could carry money or a beneficiary into a publication body. Broad on purpose: a
# false positive costs a rename, a false negative costs the rule.
DERIVED_ONLY_HINTS = (
    "amount",
    "irr",
    "toman",
    "rial",
    "total",
    "paid",
    "beneficiary",
    "iban",
    "tracking",
    "attempt",
    "hash",
    "status",
)

# The three §17 `:1153` items that live on the row and must never enter `summary_payload`. Each of
# them changes on every publication, so any one of them inside the digest would make
# `uq_publication_content_per_request` unable to fire while still looking present.
NOT_HASHABLE = ("published_at", "published_by", "publication_version", "created_at")


def _snapshot_function() -> ast.FunctionDef:
    """The `_snapshot` definition, as an AST node.

    Read from source rather than called, because calling it needs a session and every property
    below is a property of what it is *written* to return.
    """

    tree = ast.parse(COMMAND.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_snapshot":
            return node
    raise AssertionError(
        "`_snapshot` is gone from app/commands/payment_publication.py. It is the only thing that "
        "decides what a publication's hash covers; if it was renamed, this test must follow it "
        "rather than be deleted."
    )


@pytest.mark.parametrize("model", [PreviewRequest, PublishRequest])
def test_no_publication_body_accepts_a_financial_value(model: type) -> None:
    """`SVC-PUBLICATION-003`. Doc 05 §20.2, enforced by there being no field.

    Checked over the model's own fields rather than by posting a body: a model that *rejects* an
    amount and a model that has no such field are different guarantees, and only the second
    survives somebody relaxing `extra="forbid"`.
    """

    offenders = [
        name
        for name in model.model_fields
        if any(hint in name.lower() for hint in DERIVED_ONLY_HINTS)
    ]
    assert offenders == [], (
        f"{model.__name__} accepts {offenders}. `05_API_Specification.md:1889` says the server "
        "derives amount, beneficiary, attempts, status, bank, tracking and dates from "
        "authoritative records and that 'the client cannot submit arbitrary financial summary "
        "values' — a field here is a value that can disagree with the record."
    )


@pytest.mark.parametrize("model", [PreviewRequest, PublishRequest])
def test_both_bodies_forbid_unknown_fields(model: type) -> None:
    assert model.model_config.get("extra") == "forbid", (
        f"{model.__name__} would accept fields nobody wrote down. On this surface that means a "
        "publisher could send a summary value the model does not name and never be told it was "
        "ignored."
    )


def test_neither_body_offers_a_share_file_that_does_not_exist() -> None:
    """Slice 5B owns the renderer, so nothing here may take an order for one.

    `05_API_Specification.md:1893` does show `include_share_file` and `share_format`. A flag a
    caller may set that changes nothing reads as a working feature, which is worse than an absent
    one — this repository has found the same shape fifteen times in the other direction, as a
    mechanism nothing calls.
    """

    for model in (PreviewRequest, PublishRequest):
        offenders = [
            name
            for name in model.model_fields
            if "share" in name.lower() or "format" in name.lower()
        ]
        assert offenders == [], (
            f"{model.__name__} accepts {offenders} and nothing renders a share file yet. Either "
            "slice 5B has landed — in which case this test should be replaced by one that "
            "asserts the file — or the field is an order nobody fills."
        )


def test_the_hashed_payload_contains_no_key_that_changes_every_time() -> None:
    """`SVC-PUBLICATION-002`. The whole reason `uq_publication_content_per_request` can fire.

    `_snapshot` returns one dictionary literal and this reads its keys. If `published_at` ever
    joined them, the constraint that refuses a correction which changed nothing would still be in
    the migration, still be reported by the schema test, and never refuse anything again.
    """

    node = _snapshot_function()
    keys: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Dict):
            keys.extend(
                str(key.value)
                for key in child.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )

    offenders = sorted(
        {key for key in keys if any(banned in key for banned in NOT_HASHABLE)}
    )
    assert offenders == [], (
        f"`_snapshot` puts {offenders} into the hashed payload. Each of those changes on every "
        "publication, so `UNIQUE(payment_request_id, content_hash)` — the constraint "
        "`04_Database_Schema.md:1155` gives for refusing a republished identical snapshot — could "
        "never fire again. They belong on the row, where the API reads them from."
    )


def test_the_payload_masks_the_iban_at_write_time() -> None:
    """§17 `:1153`: "masked IBAN according to policy", and the mask happens before storage.

    A read-time mask would leave the full account number in a JSONB column retained for years —
    `app/db/models/audit_log.py` gives that argument for the audit trail and it is stronger here,
    because this row is handed to somebody outside the company.
    """

    source = COMMAND.read_text(encoding="utf-8")
    node = _snapshot_function()
    masked = any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "mask_iban_value"
        for child in ast.walk(node)
    )
    assert masked, (
        "`_snapshot` no longer calls `mask_iban_value`. The beneficiary IBAN would be stored in "
        "full in `summary_payload` and every later reader would be one careless serializer away "
        "from handing it to a trader."
    )
    assert "beneficiary_iban_masked" in source, (
        "the payload key that carried the masked IBAN is gone; §17 `:1153` requires the field, "
        "masked."
    )


def test_the_migration_grants_no_update_on_the_publication_table() -> None:
    """§11.9's first word. Immutability is a privilege the runtime does not hold.

    Slice 1 set the precedent by granting nothing on `payment_attempts`, which is what made
    "accepting a candidate does not mark an attempt paid" impossible rather than merely
    unimplemented. Slice 7 adds `GRANT UPDATE (status)` with the correction that needs it — and
    if it arrives early, this test is what says so.
    """

    source = MIGRATION.read_text(encoding="utf-8")
    statements = [
        line
        for line in source.splitlines()
        if "GRANT" in line and "payment_result_publications" in line
    ]
    assert statements == [], (
        f"{MIGRATION.name} issues {statements}. `04_Database_Schema.md:1135` calls these rows "
        "immutable; a runtime role that may UPDATE them makes that a description of intent "
        "rather than of the database."
    )


def test_publication_is_reachable_only_from_paid_and_says_why() -> None:
    """`SVC-PUBLICATION-004`, and the guard on G-5's decision.

    A failed payment is told to its trader through `notifications`, not published — the argument is
    in the M9 plan and the short version is that a publication is an immutable hashed artifact with
    evidence attached, and a failure has none of that to carry. `PaymentAttemptFailed` has been
    enqueued since slice 3 and slice 7 is its consumer.

    The obvious future edit is to add `failed` to these tuples, because the refusal looks unkind.
    This test is what makes that edit deliberate: widening the set means changing this line, and
    changing this line means reading G-5. The refusal message is asserted too, so the person who
    hits it in production is pointed at the notification path rather than left to infer that
    publication is coming.
    """

    from app.commands.payment_publication import PREVIEWABLE_FROM, PUBLISHABLE_FROM

    assert set(PREVIEWABLE_FROM) == {"paid", "result_ready_for_trader"}, (
        f"publication became reachable from {sorted(PREVIEWABLE_FROM)}. G-5 in the M9 plan "
        "decides that only a completed settlement is published and a failure is notified; "
        "widening this is a product decision, not a bug fix."
    )
    assert set(PUBLISHABLE_FROM) == {"result_ready_for_trader"}, (
        f"publishing became reachable from {sorted(PUBLISHABLE_FROM)}, so the preview — the step "
        "that validates the snapshot — can be skipped."
    )

    source = COMMAND.read_text(encoding="utf-8")
    assert "notifications" in source and "PaymentAttemptFailed" in source, (
        "the refusal no longer names where a failure does go. A caller told only 'this is not "
        "publishable' will reasonably conclude the trader is never told, and the next change will "
        "be to add the branch this test exists to make deliberate."
    )


def test_the_router_documents_no_status_code_it_cannot_return() -> None:
    """A route advertising a 202 it never sends is paperwork with no caller.

    Doc 05 §20.2 permits `202` "if share-file generation is asynchronous". Nothing in this slice
    is asynchronous, so the route is `201` and the responses table must not promise otherwise —
    a client written against a 202 would wait for a callback that never comes.

    Read from the AST rather than by searching the text, because the first version of this test
    did search the text — and matched `20260801_0008:250-251`, the citation for the permission
    seed. A scan that cannot tell a status code from a line number is the same class of mistake as
    the obligation-id scan that counted the comment explaining its own collision.
    """

    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    declared: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            declared.update(
                key.value
                for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, int)
            )
        elif isinstance(node, ast.Call):
            declared.update(
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "status_code"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, int)
            )

    assert 202 not in declared, (
        "the publication router declares a 202. Either share-file rendering became asynchronous — "
        "in which case the status code, the OpenAPI contract and this test all change together — "
        "or the route promises a shape it does not produce."
    )
    assert 201 in declared, (
        "the publish route no longer declares 201. `05_API_Specification.md:1901` allows 201 or "
        "202 and this slice produces the row before returning, which is 201."
    )
