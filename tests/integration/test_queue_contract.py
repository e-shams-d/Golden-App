"""The queue contract, asserted against a real database. M11 slice 2.

`15_Agent_Implementation_Plan.md:1256` (§19), and the plan's **G-1**.

§19.2 names twenty-four queues; document 05 defines a route for none of them. So this file is not
testing an approved contract — it is testing **the one this slice decided**, which is why the
decision is asserted here rather than only described in a docstring. If the owner reverses G-1, the
failures name the paths.

**§19 `:1298`'s six rules get six assertions, not one.** A single "the queue paginates" test passes
against an implementation missing four of them. The rules are: cursor pagination, stable ordering,
allowlisted filters, allowlisted sorting, permission-aware counts, and no unbounded read.

**The ordering test seeds rows that share a timestamp.** A stable-ordering assertion over rows a
second apart passes against a sort with no tiebreak at all, because every page boundary lands
somewhere unambiguous. Ties are the only condition under which instability is observable, and a
work queue — where a trader submits several requests in one sitting — is where ties actually occur.

**Slice 3 added the accountant's other ten.** Each queue is asserted to return rows in the state it
names *and to exclude the adjacent one* — the first half alone passes against a query returning
everything, which is why the exclusions are separate assertions, and why `new-requests` and
`correction-responses` are checked as a **partition** rather than one at a time.

**Slice 3B built the three fixture chains slice 3 could not**, so all eleven queues now have rows
and every predicate is asserted on which rows it selects. `bank_excel_exports` needs a batch
version, a bank profile version, a mapping, a file object, an approval and an admin;
`payment_attempts` needs a request and a revision behind a composite key;
`incoming_payment_receipts` needs a gold-sale order.

**Slice 3 blamed the wrong cause for its uncaught control, and the fixture is what showed it.**
That commit said deleting `sent_to_bank_marked_at IS NULL` from the exports queue went NOT CAUGHT
because no export row existed. With rows, it still would: `mark_sent` sets the timestamp *and*
`status = sent_to_bank_marked` in one statement (`app/commands/bank_export.py:657`), so the status
filter already excludes every sent export and the timestamp can never be what excludes one. That is
a sabotage which does not break the property — meaning 3 of the four — rather than a missing test.

The condition stays, because it is free and it is what would matter if the two facts ever stopped
moving together. `test_marking_sent_moves_both_facts_together` is the assertion that would notice.

Covers: API-QUEUE-001, SEC-QUEUE-001, SVC-QUEUE-001.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic_runner import run_alembic
from bootstrap_replay import RuntimeIdentities

pytestmark = pytest.mark.integration

PASSWORD = "correct-horse-battery-staple"
ADMIN_CSRF_COOKIE = "__Host-gp_admin_csrf"
TRADER_CSRF_COOKIE = "__Host-gp_trader_csrf"

TRADER_PHONE = "+989120041001"
OTHER_PHONE = "+989120041002"
# `IR` plus twenty-four digits, which is what `ck_beneficiaries_normalized_iban_shape` enforces.
IBANS = {
    "trader": "IR060120000000000000000101",
    "other": "IR060120000000000000000102",
}
ACCOUNTANT = "queue_accountant"
# `permission_catalog.yaml:444` gives `payment_request.read` to four roles. The warehouse operator
# holds none of them, which makes it the honest "authenticated but ungranted" admin for the
# permission negative — a role that exists rather than one invented for the test.
UNGRANTED_ADMIN = "queue_warehouse"
MANAGER = "queue_manager"
TECHNICAL_ADMIN = "queue_technical"

# M11 slice 4. Which role is expected to reach which queue. Written out rather than derived from
# the registry, because deriving it from the thing under test would make the assertion circular —
# a queue guarded by the wrong permission would move in both the code and the expectation.
ACCOUNTANT_QUEUES = frozenset(
    {
        "new-requests",
        "correction-responses",
        "eligible-for-batching",
        "draft-invalid-batch-versions",
        "approved-exports-awaiting-send",
        "sent-attempts-awaiting-result",
        "unresolved-bundles-segments",
        "failed-partial-retry-payments",
        "incoming-receipts-requiring-review",
        "trader-disputes",
        "reconciliation-tasks",
        # The manager's approval queue is `payment_batch_version.read_approval_view`, which the
        # catalogue gives to the accountant as well — reading who is waiting is not approving.
        "batch-versions-awaiting-approval",
    }
)
WAREHOUSE_QUEUES = frozenset(
    {"orders-ready-for-dispatch", "blocked-dispatches", "receipt-confirmation-work"}
)
# M11 slice 5. One queue, and the role that holds it holds nothing else here.
TECHNICAL_QUEUES = frozenset({"quarantined-files-exports"})

QUEUE = "/api/v1/queues/new-requests"

SUBMITTED = "submitted_to_center"
# The adjacent state, and the whole reason the queue is asserted as an exclusion rather than only
# as an inclusion. A request somebody is already reviewing is not new; a queue that returns it hands
# two people the same work. Slice 3 owes this same shape for the accountant's other ten.
UNDER_REVIEW = "under_accountant_review"


@pytest.fixture(scope="module")
def migrated(module_provisioned_database: RuntimeIdentities) -> RuntimeIdentities:
    result = run_alembic(
        module_provisioned_database.migrator_url,
        "upgrade",
        "head",
        app_role=module_provisioned_database.app_role,
        worker_role=module_provisioned_database.worker_role,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    return module_provisioned_database


@pytest.fixture(scope="module")
def world(migrated: RuntimeIdentities, tmp_path_factory: Any) -> Iterator[dict[str, Any]]:
    from app.core.config import Settings
    from app.core.runtime import RuntimeServices
    from app.main import create_app
    from app.security.passwords import Argon2Parameters, hash_password
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=migrated.owner_url,
        redis_url="redis://127.0.0.1:6379/0",
        local_storage_root=tmp_path_factory.mktemp("queue-storage"),
        release_commit="abcdef1234567",
        log_level="CRITICAL",
        auth_csrf_key_secret="y" * 40,
        auth_rate_limit_key_secret=None,
    )
    parameters = Argon2Parameters.from_settings(settings)
    encoded = hash_password(PASSWORD, parameters, max_length=settings.password_max_length)

    ids: dict[str, uuid.UUID] = {}

    with psycopg.connect(_psycopg(migrated.owner_url)) as connection:
        for key, phone, name in (
            ("trader", TRADER_PHONE, "First Business"),
            ("other", OTHER_PHONE, "Second Business"),
        ):
            trader_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO traders (id, display_name, primary_phone, operational_status, "
                "approval_status) VALUES (%s, %s, %s, 'active', 'approved')",
                (trader_id, name, phone),
            )
            connection.execute(
                "INSERT INTO trader_users (trader_id, phone_number, full_name, password_hash, "
                "status, is_primary) VALUES (%s, %s, %s, %s, 'active', TRUE)",
                (trader_id, phone, name, encoded),
            )
            ids[key] = trader_id

            # `payment_requests.beneficiary_id` is NOT NULL — a request is always *to* somebody.
            # One per trader, because a beneficiary belongs to the business that entered it.
            beneficiary_id = uuid.uuid4()
            # `ck_beneficiaries_normalized_iban_shape` wants `IR` and twenty-four digits. A
            # generated one with a letter in it fails the CHECK, which is the constraint doing its
            # job — so these are written out rather than derived from the fixture key.
            iban = IBANS[key]
            connection.execute(
                "INSERT INTO beneficiaries (id, trader_id, full_name, iban, normalized_iban, "
                "status, verification_status) VALUES (%s, %s, %s, %s, %s, 'active', "
                "'not_checked')",
                (beneficiary_id, trader_id, f"{name} Payee", iban, iban),
            )
            ids[f"{key}_beneficiary"] = beneficiary_id

        # M11 slice 4 adds a manager and a warehouse operator, because its queues are theirs. The
        # "ungranted" admin is now the *manager* for warehouse queues and the *warehouse* for the
        # accountant's — no single role is ungranted everywhere, which is the point of the split.
        for username, role in (
            (ACCOUNTANT, "accountant"),
            (UNGRANTED_ADMIN, "warehouse_operator"),
            (MANAGER, "manager"),
            (TECHNICAL_ADMIN, "technical_admin"),
        ):
            connection.execute(
                "INSERT INTO admin_users (username, full_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'active')",
                (username, username, encoded),
            )
            connection.execute(
                "INSERT INTO admin_user_roles (admin_user_id, role_id) "
                "SELECT u.id, r.id FROM admin_users u, roles r "
                "WHERE u.username = %s AND r.code = %s",
                (username, role),
            )
        # --- The chains slice 3 could not build -------------------------------------------
        #
        # M11 slice 3B. Slice 3 seeded only `payment_requests`, `manual_review_tasks` and
        # `bank_result_bundles`, because those need one or two statements. The other three queue
        # tables need four to six rows of scaffolding each, and the consequence was not a gap
        # anybody would have noticed — it was a negative control going **NOT CAUGHT**: deleting
        # `sent_to_bank_marked_at IS NULL` from the exports queue changed nothing, because no
        # export row existed for the predicate to filter.
        #
        # Everything below exists so that three queue predicates have rows to select. None of it
        # is asserted on; it is scaffolding, written once here rather than per test so the tests
        # read as statements about queues.
        for key in ("bank", "version", "mapping", "account", "batch", "batch_version", "file"):
            ids[key] = uuid.uuid4()

        connection.execute(
            "INSERT INTO bank_profiles (id, code, name, status) "
            "VALUES (%s, 'queuebank', 'Queue Bank', 'active')",
            (ids["bank"],),
        )
        connection.execute(
            "INSERT INTO bank_profile_versions (id, bank_profile_id, version_number, status, "
            "config_hash) VALUES (%s, %s, 1, 'active', %s)",
            (ids["version"], ids["bank"], "a" * 64),
        )
        connection.execute(
            "INSERT INTO bank_mappings (id, bank_profile_version_id, file_type, "
            "template_version, status, mapping, config_hash) "
            "VALUES (%s, %s, 'payment_export', 1, 'active', '{}', %s)",
            (ids["mapping"], ids["version"], "b" * 64),
        )
        connection.execute(
            "INSERT INTO bank_accounts (id, bank_profile_id, display_name, account_role, status) "
            "VALUES (%s, %s, 'Outgoing', 'outgoing_source', 'active')",
            (ids["account"], ids["bank"]),
        )
        connection.execute(
            "INSERT INTO payment_batches (id, batch_number, status, created_by_admin_user_id) "
            "SELECT %s, 'B-QUEUE-1', 'draft', u.id FROM admin_users u WHERE u.username = %s",
            (ids["batch"], ACCOUNTANT),
        )
        connection.execute(
            "INSERT INTO payment_batch_versions (id, payment_batch_id, version_number, "
            "bank_profile_version_id, bank_account_id, bank_mapping_id, status, row_count, "
            "total_amount_irr, content_hash, created_by_admin_user_id) "
            # `ck_payment_batch_versions_row_count` refuses an empty version — a batch version
            # with no rows is not a thing anybody would send to a bank.
            "SELECT %s, %s, 1, %s, %s, %s, 'draft', 1, 1000000, %s, u.id FROM admin_users u "
            "WHERE u.username = %s",
            (
                ids["batch_version"],
                ids["batch"],
                ids["version"],
                ids["account"],
                ids["mapping"],
                "c" * 64,
                ACCOUNTANT,
            ),
        )
        # A **final** export must name an approval: `ck_bank_excel_exports_approval_matches_type`
        # is M7's separation-of-duties rule expressed as a CHECK, and the approval's composite
        # foreign keys tie it to the exact version's finalizer, creator and content hash. So the
        # version has to record a finalizer before an approval can reference one.
        # A second version, because `uq_active_final_export_per_version` permits one live final
        # export per version and one test needs two exports.
        ids["second"] = uuid.uuid4()
        connection.execute(
            "INSERT INTO payment_batch_versions (id, payment_batch_id, version_number, "
            "bank_profile_version_id, bank_account_id, bank_mapping_id, status, row_count, "
            "total_amount_irr, content_hash, created_by_admin_user_id) "
            "SELECT %s, %s, 2, %s, %s, %s, 'approved', 1, 1000000, %s, u.id FROM admin_users u "
            "WHERE u.username = %s",
            (
                ids["second"],
                ids["batch"],
                ids["version"],
                ids["account"],
                ids["mapping"],
                "9" * 64,
                ACCOUNTANT,
            ),
        )
        for version_key, content_hash in (("batch_version", "c" * 64), ("second", "9" * 64)):
            approval_id = uuid.uuid4()
            connection.execute(
                "UPDATE payment_batch_versions SET finalized_by_admin_user_id = "
                "(SELECT id FROM admin_users WHERE username = %s) WHERE id = %s",
                (ACCOUNTANT, ids[version_key]),
            )
            connection.execute(
                "INSERT INTO batch_approvals (id, payment_batch_version_id, decision, "
                "decided_by_admin_user_id, decided_at, authentication_context, "
                "version_finalized_by_admin_user_id, version_created_by_admin_user_id, "
                "approved_content_hash) "
                "SELECT %s, %s, 'approved', d.id, now(), '{}', a.id, a.id, %s "
                "FROM admin_users d, admin_users a WHERE d.username = %s AND a.username = %s",
                (
                    approval_id,
                    ids[version_key],
                    content_hash,
                    UNGRANTED_ADMIN,
                    ACCOUNTANT,
                ),
            )
            ids[f"approval_{version_key}"] = approval_id
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            "VALUES (%s, 'local', 'gold', %s, 'export.xlsx', "
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 4096, %s, "
            "'bank_export', 'internal', 'available', 'clean', 'admin_user', 'original', '{}')",
            (ids["file"], f"exports/{ids['file']}", "d" * 64),
        )
        for key in ("trader", "other"):
            order_id = uuid.uuid4()
            connection.execute(
                "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
                "gold_weight, weight_unit, gold_purity, created_by_actor_type) "
                # `SEED-`, so the per-test cleanup can delete every `GS-` order without taking the
                # two the receipt helper depends on with it.
                "VALUES (%s, %s, %s, 'draft', 'bullion', 10.0, 'GRAM', '750', 'trader_user')",
                (order_id, ids[key], f"SEED-{uuid.uuid4().hex[:8]}"),
            )
            ids[f"{key}_order"] = order_id
        connection.commit()

    app = create_app(settings=settings)
    app.state.runtime = RuntimeServices.from_settings(settings)
    app.state.accepting_traffic = True
    with TestClient(app, base_url="https://admin.localhost") as client:
        yield {
            "client": client,
            "runtime": app.state.runtime,
            "owner_url": migrated.owner_url,
            **{f"{name}_id": value for name, value in ids.items()},
        }
    app.state.runtime.close()


def _psycopg(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(autouse=True)
def an_empty_queue(world: dict[str, Any]) -> Iterator[None]:
    """The database is module-scoped, so a count assertion counts earlier tests without this."""

    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        # Order matters: attempts reference requests, and exports reference nothing that is
        # deleted here, but deleting requests first would violate the attempt's foreign key.
        connection.execute("DELETE FROM bank_excel_exports")
        connection.execute("DELETE FROM payment_attempts")
        connection.execute("DELETE FROM payment_request_revisions")
        connection.execute("DELETE FROM incoming_payment_receipts")
        connection.execute("DELETE FROM payment_requests")
        connection.execute("DELETE FROM manual_review_tasks")
        connection.execute(
            "DELETE FROM file_objects WHERE storage_key LIKE 'files/%'"
        )
        connection.execute("DELETE FROM bank_result_bundles")
        # Dispatches before orders: the dispatch's foreign key points at the order.
        connection.execute("DELETE FROM gold_dispatches")
        connection.execute("DELETE FROM incoming_payment_receipts")
        connection.execute("DELETE FROM gold_sale_orders WHERE order_number LIKE 'GS-%'")
        connection.execute(
            "DELETE FROM payment_batch_versions WHERE version_number > 2"
        )
        connection.commit()
    yield


def request_row(
    world: dict[str, Any],
    *,
    status: str = SUBMITTED,
    trader: str = "trader",
    created_at: datetime | None = None,
    number: str | None = None,
) -> uuid.UUID:
    """One payment request, written directly.

    Seeded rather than walked through M5's commands on purpose: this file tests the *queue* — who
    may read it, how it pages, what it excludes — and driving eight commands per row would test M5
    a second time while making the tie-breaking and pagination cases impractical to construct.
    `tests/integration/test_payment_requests.py` owns the lifecycle.
    """

    request_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_requests (id, trader_id, beneficiary_id, request_number, "
            "status, created_at) VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()))",
            (
                request_id,
                world[f"{trader}_id"],
                world[f"{trader}_beneficiary_id"],
                number or f"PR-{uuid.uuid4().hex[:10]}",
                status,
                created_at,
            ),
        )
        connection.commit()
    return request_id


def task_row(world: dict[str, Any], *, task_type: str, status: str = "open") -> uuid.UUID:
    """One manual review task. No foreign keys of its own, so it seeds in a single statement."""

    task_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            # `record_version` is NOT NULL with no server default — the ORM supplies it, and a raw
            # insert has to say so.
            "INSERT INTO manual_review_tasks (id, task_type, priority, status, entity_type, "
            "entity_id, title, record_version) "
            "VALUES (%s, %s, 3, %s, 'payment_attempt', %s, 'seeded', 1)",
            (task_id, task_type, status, uuid.uuid4()),
        )
        connection.commit()
    return task_id


def bundle_row(world: dict[str, Any], *, status: str) -> uuid.UUID:
    """One bank result bundle. Needs a bank profile and an uploader, both seeded in `world`."""

    bundle_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO bank_result_bundles (id, bundle_number, bank_profile_id, status, "
            "source_type, uploaded_by_admin_user_id, uploaded_at, segment_count, "
            "resolved_segment_count, unresolved_segment_count, record_version) "
            "SELECT %s, %s, %s, %s, 'manual_upload', u.id, now(), 0, 0, 0, 1 FROM admin_users u "
            "WHERE u.username = %s",
            (bundle_id, f"B-{uuid.uuid4().hex[:8]}", world["bank_id"], status, ACCOUNTANT),
        )
        connection.commit()
    return bundle_id


def export_row(
    world: dict[str, Any],
    *,
    status: str,
    export_type: str = "final",
    sent: bool = False,
    version: str = "batch_version",
) -> uuid.UUID:
    """One bank export. `sent` sets `sent_to_bank_marked_at`, which is the queue's third condition.

    `version` selects which batch version the export belongs to, because
    `uq_active_final_export_per_version` permits one live final export per version — a real rule,
    and the reason two exports in one test need two versions.
    """

    export_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO bank_excel_exports (id, payment_batch_version_id, batch_approval_id, "
            "bank_profile_version_id, bank_mapping_id, file_id, export_number, export_type, "
            "row_count, total_amount_irr, content_hash, file_sha256_hash, status, "
            "generated_by_admin_user_id, generated_at, sent_to_bank_marked_at) "
            "SELECT %s, %s, %s, %s, %s, %s, %s, %s, 1, 1000000, %s, %s, %s, u.id, now(), %s "
            "FROM admin_users u WHERE u.username = %s",
            (
                export_id,
                world[f"{version}_id"],
                # A preview must carry no approval; a final must carry one. The same CHECK reads
                # both ways, which is why this follows `export_type` rather than being constant.
                world[f"approval_{version}_id"] if export_type == "final" else None,
                world["version_id"],
                world["mapping_id"],
                world["file_id"],
                f"EX-{uuid.uuid4().hex[:8]}",
                export_type,
                "e" * 64,
                "f" * 64,
                status,
                datetime.now(UTC) if sent else None,
                ACCOUNTANT,
            ),
        )
        connection.commit()
    return export_id


def attempt_row(world: dict[str, Any], *, status: str) -> uuid.UUID:
    """One payment attempt, with the request and revision its composite key needs."""

    attempt_id = uuid.uuid4()
    request_id = request_row(world, status="batched")
    revision_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO payment_request_revisions (id, payment_request_id, revision_number, "
            "beneficiary_id, beneficiary_name_snapshot, beneficiary_iban_snapshot, amount_irr, "
            "content_hash, created_by_actor_type) "
            "VALUES (%s, %s, 1, %s, 'Payee', %s, 1000000, %s, 'trader_user')",
            (
                revision_id,
                request_id,
                world["trader_beneficiary_id"],
                IBANS["trader"],
                "1" * 64,
            ),
        )
        connection.execute(
            "INSERT INTO payment_attempts (id, payment_request_id, payment_request_revision_id, "
            "attempt_number, attempt_type, amount_irr, beneficiary_name_snapshot, "
            "beneficiary_iban_snapshot, bank_profile_version_id, status) "
            "VALUES (%s, %s, %s, 1, 'original', 1000000, 'Payee', %s, %s, %s)",
            (
                attempt_id,
                request_id,
                revision_id,
                IBANS["trader"],
                world["version_id"],
                status,
            ),
        )
        connection.commit()
    return attempt_id


def receipt_row(world: dict[str, Any], *, status: str, trader: str = "trader") -> uuid.UUID:
    """One incoming payment receipt against a seeded gold-sale order."""

    receipt_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO incoming_payment_receipts (id, gold_sale_order_id, trader_id, "
            "amount_irr, status) VALUES (%s, %s, %s, 5000000, %s)",
            (receipt_id, world[f"{trader}_order_id"], world[f"{trader}_id"], status),
        )
        connection.commit()
    return receipt_id


def quarantined_file(
    world: dict[str, Any], *, filename: str, scan_status: str = "quarantined"
) -> uuid.UUID:
    """One file object in a named scan state. `file_objects` carries no `trader_id`."""

    file_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO file_objects (id, storage_provider, storage_bucket, storage_key, "
            "original_filename, mime_type_declared, size_bytes, sha256_hash, category, "
            "visibility_scope, storage_status, scan_status, uploaded_by_actor_type, "
            "original_or_derived_relation, metadata) "
            # `ck_file_objects_available_requires_clean_scan`: a file cannot be `available` while
            # its scan says `quarantined`. The constraint is the schema refusing to let an
            # unchecked file look usable, which is ADR-008's interim rule in DDL.
            "VALUES (%s, 'local', 'gold', %s, %s, 'application/pdf', 2048, %s, "
            "'payment_evidence', 'internal', %s, %s, 'trader_user', 'original', '{}')",
            (
                file_id,
                f"files/{file_id}",
                filename,
                uuid.uuid4().hex * 2,
                "available" if scan_status == "clean" else "quarantined",
                scan_status,
            ),
        )
        connection.commit()
    return file_id


def batch_version_row(world: dict[str, Any], *, status: str) -> uuid.UUID:
    """One more version of the seeded batch. Version numbers climb so the unique holds."""

    version_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        row = connection.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM payment_batch_versions "
            "WHERE payment_batch_id = %s",
            (world["batch_id"],),
        ).fetchone()
        assert row is not None
        connection.execute(
            "INSERT INTO payment_batch_versions (id, payment_batch_id, version_number, "
            "bank_profile_version_id, bank_account_id, bank_mapping_id, status, row_count, "
            "total_amount_irr, content_hash, created_by_admin_user_id) "
            "SELECT %s, %s, %s, %s, %s, %s, %s, 1, 1000000, %s, u.id FROM admin_users u "
            "WHERE u.username = %s",
            (
                version_id,
                world["batch_id"],
                row[0],
                world["version_id"],
                world["account_id"],
                world["mapping_id"],
                status,
                uuid.uuid4().hex + uuid.uuid4().hex,
                ACCOUNTANT,
            ),
        )
        connection.commit()
    return version_id


def order_row(world: dict[str, Any], *, status: str, trader: str = "trader") -> uuid.UUID:
    """One gold sale order in a named state."""

    order_id = uuid.uuid4()
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_sale_orders (id, trader_id, order_number, status, gold_type, "
            "gold_weight, weight_unit, gold_purity, created_by_actor_type) "
            "VALUES (%s, %s, %s, %s, 'bullion', 10.0, 'GRAM', '750', 'trader_user')",
            (order_id, world[f"{trader}_id"], f"GS-{uuid.uuid4().hex[:8]}", status),
        )
        connection.commit()
    return order_id


def dispatch_row(world: dict[str, Any], *, status: str) -> uuid.UUID:
    """One gold dispatch against a freshly seeded order."""

    dispatch_id = uuid.uuid4()
    order_id = order_row(world, status="dispatched")
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "INSERT INTO gold_dispatches (id, gold_sale_order_id, dispatch_type, status, "
            "created_by_admin_user_id) "
            "SELECT %s, %s, 'physical_dispatch', %s, u.id FROM admin_users u "
            "WHERE u.username = %s",
            (dispatch_id, order_id, status, UNGRANTED_ADMIN),
        )
        connection.commit()
    return dispatch_id


def sign_in(world: dict[str, Any], username: str) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/admin/login", json={"identifier": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_trader(world: dict[str, Any], phone: str = TRADER_PHONE) -> None:
    client = world["client"]
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/trader/login", json={"identifier": phone, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text


# --- SEC-QUEUE-001: who may read it, and what the allowlist does with an unknown key -------


def built_queue_names() -> list[str]:
    from app.queues.registry import BUILT

    return sorted(BUILT)


def test_no_trader_can_reach_any_queue(world: dict[str, Any]) -> None:
    """**Every** queue, swept from the registry rather than named path by path.

    This is the assertion `test_ownership_scope.py`'s `QUEUE_SCOPE_EXEMPT` rests on. Each entry
    there argues a queue needs no `scoped()` call *because no trader can reach it*; without this
    sweep those are claims about grants nobody checked.

    Swept rather than enumerated so that a queue added in slice 4 is covered the moment it is
    registered. A per-path test would have to be remembered, and the one nobody remembers is the
    one that leaks.
    """

    names = built_queue_names()
    assert len(names) >= 11, f"the sweep is checking almost nothing: {names}"

    sign_in_trader(world)
    reachable = [
        name
        for name in names
        if world["client"].get(f"/api/v1/queues/{name}").status_code != 403
    ]
    assert reachable == [], f"a trader reached these internal queues: {reachable}"


def test_each_role_reaches_its_own_queues_and_no_others(world: dict[str, Any]) -> None:
    """The positive and negative halves together, per role. M11 slice 4.

    **A 403 sweep alone proves nothing about correctness.** It passes perfectly against a router
    that refuses everybody — including one where a queue is guarded by a permission *nobody* holds,
    which this project has shipped before: `bank_profile.activate_version` is granted to no role
    and its route denies every caller. So each role is asserted to reach exactly its own set.

    Slice 4 is where this stops being one set. The warehouse's three are guarded by
    `gold_sale.dispatch`, so the accountant must *not* reach them — before slice 4 the accountant
    reached everything, and a single "the accountant can reach every queue" assertion would now be
    wrong rather than merely weak.
    """

    names = set(built_queue_names())
    assert names == ACCOUNTANT_QUEUES | WAREHOUSE_QUEUES | TECHNICAL_QUEUES, (
        "the expected sets have drifted from the registry; a queue was added without deciding "
        f"whose it is: "
        f"{sorted(names ^ (ACCOUNTANT_QUEUES | WAREHOUSE_QUEUES | TECHNICAL_QUEUES))}"
    )

    audiences = (
        (ACCOUNTANT, ACCOUNTANT_QUEUES),
        (UNGRANTED_ADMIN, WAREHOUSE_QUEUES),
        (TECHNICAL_ADMIN, TECHNICAL_QUEUES),
    )
    for username, expected in audiences:
        sign_in(world, username)
        reached = {
            name
            for name in names
            if world["client"].get(f"/api/v1/queues/{name}").status_code == 200
        }
        assert reached == expected, (
            f"{username} reached {sorted(reached - expected)} it should not, and could not reach "
            f"{sorted(expected - reached)} it should"
        )


def test_an_admin_without_the_grant_is_refused(world: dict[str, Any]) -> None:
    """Authenticated is not authorised. A warehouse operator holds no `payment_request.read`."""

    request_row(world)
    sign_in(world, UNGRANTED_ADMIN)

    response = world["client"].get(QUEUE)
    assert response.status_code == 403, response.text


def test_an_unauthenticated_caller_is_refused(world: dict[str, Any]) -> None:
    request_row(world)
    world["client"].cookies.clear()

    assert world["client"].get(QUEUE).status_code == 401


def test_a_sort_key_that_is_not_allowlisted_is_refused(world: dict[str, Any]) -> None:
    """SEC-QUEUE-001. Refused, not ignored — and `status` is chosen to make that sharp.

    `status` is a real column of `payment_requests`, so a 400 here is the allowlist doing its job
    rather than the name failing to resolve. An implementation that ignored it would return the
    default ordering and a 200, which looks identical to success from the caller's side.
    """

    request_row(world)
    sign_in(world, ACCOUNTANT)

    response = world["client"].get(QUEUE, params={"sort": "status"})
    assert response.status_code == 400, response.text


def test_a_filter_that_is_not_allowlisted_is_not_silently_applied(world: dict[str, Any]) -> None:
    """The queue's defining status is deliberately not a filter.

    `/queues/new-requests?status=paid` must not be a way to reach a different queue through the
    wrong name. FastAPI does not bind an undeclared query parameter, so the guarantee is that the
    parameter changes nothing — asserted by comparing against the unfiltered page rather than by a
    status code, because "ignored" and "refused" are both acceptable answers here and "applied" is
    not.
    """

    request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    plain = world["client"].get(QUEUE)
    smuggled = world["client"].get(QUEUE, params={"status": UNDER_REVIEW})
    assert plain.status_code == 200, plain.text
    assert smuggled.status_code in (200, 400), smuggled.text
    if smuggled.status_code == 200:
        assert smuggled.json()["items"] == plain.json()["items"]
        assert [item["status"] for item in smuggled.json()["items"]] == [SUBMITTED]


# --- API-QUEUE-001: §19 :1298's six rules, one assertion each ------------------------------


def test_the_contract_refuses_a_filter_the_queue_does_not_allowlist(
    world: dict[str, Any],
) -> None:
    """`read_queue_page`'s allowlist check, asserted where it can actually be reached.

    **This test exists because a negative control went NOT CAUGHT.** Deleting
    `definition.spec.require_filterable(name)` from `read_queue_page` changed nothing, and the
    reason is that the route cannot express the attack: FastAPI binds only declared query
    parameters, so the one filter that ever reaches the contract is `trader_id`, which *is*
    allowlisted. The route-level test above therefore cannot fail, whatever the contract does.

    That does not make the guard unnecessary — it makes it untested. Slices 3 to 5 add twenty-three
    more queues, each with its own `filters` frozenset, and the first route that builds its filter
    dict from several parameters will hand this function a name some other queue allowlists and
    this one does not. So the guard is called directly, one layer below the route, which is the
    only place the wrong input can be constructed.
    """

    from app.db.models.payment_request import PaymentRequest as PR
    from app.db.pagination import InvalidListParameterError
    from app.queues.contract import read_queue_page
    from app.queues.payment_requests import NEW_REQUESTS
    from sqlalchemy import select as sa_select

    request_row(world)
    actor = _any_actor(world)

    with world["runtime"].uow_factory() as uow:
        with pytest.raises(InvalidListParameterError):
            read_queue_page(
                uow.session,
                NEW_REQUESTS,
                sa_select(PR),
                actor=actor,
                # A real column of the table, and deliberately not in the queue's `filters`. The
                # queue is *defined* by its status; letting a caller filter on it would make this
                # path a way to reach a different queue through the wrong name.
                filters={"status": UNDER_REVIEW},
            )
        uow.rollback()


def _any_actor(world: dict[str, Any]) -> Any:
    """An `ActorContext` for a direct call, since `read_queue_page` takes one.

    The value is irrelevant to this queue — `_submitted_and_unclaimed` discards the actor, because
    no trader can reach the route to be scoped — but the signature requires one, and building it
    here keeps that fact visible rather than hiding it behind a mock.
    """

    from app.security.actor import ActorContext, ActorType, Audience

    return ActorContext(
        actor_type=ActorType.ADMIN_USER,
        actor_id=uuid.uuid4(),
        audience=Audience.ADMIN,
        session_id=uuid.uuid4(),
        security_stamp_version=1,
    )


def test_new_requests_and_correction_responses_partition_the_same_status(
    world: dict[str, Any],
) -> None:
    """The defect slice 2 merged, and the reason these two queues are written next to each other.

    §19.2 lists "new requests" and "correction responses" as **two** queues. Both are
    `submitted_to_center`: a request handed back for correction returns to that status when the
    trader resubmits. Slice 2's queue filtered on status alone, so it returned both, and the
    correction-responses queue would have returned a subset of it.

    Two overlapping queues are worse than one that is too wide — the accountant works the first,
    the second still shows the same rows, and the work is done twice or not at all. The assertion
    is therefore on the **partition**: every row appears in exactly one of them, and together they
    are the whole status.
    """

    fresh = request_row(world)
    returned = request_row(world)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET review_note = 'please fix the IBAN' WHERE id = %s",
            (returned,),
        )
        connection.commit()

    sign_in(world, ACCOUNTANT)
    new = {i["id"] for i in world["client"].get(QUEUE).json()["items"]}
    corrections = {
        i["id"]
        for i in world["client"].get("/api/v1/queues/correction-responses").json()["items"]
    }

    assert new == {str(fresh)}
    assert corrections == {str(returned)}
    assert new & corrections == set(), "a request is in both queues, so it is worked twice"
    assert new | corrections == {str(fresh), str(returned)}, "a request is in neither queue"


def test_a_request_under_review_is_in_neither_submitted_queue(world: dict[str, Any]) -> None:
    """Somebody has it. `under_accountant_review` is the adjacent state for both queues above."""

    claimed = request_row(world, status=UNDER_REVIEW)
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET review_note = 'looking at it' WHERE id = %s",
            (claimed,),
        )
        connection.commit()

    sign_in(world, ACCOUNTANT)
    for name in ("new-requests", "correction-responses"):
        body = world["client"].get(f"/api/v1/queues/{name}").json()
        assert body["items"] == [], f"{name} returned a request under review"
        assert body["total"] == 0


def test_eligible_for_batching_names_its_own_state(world: dict[str, Any]) -> None:
    """And excludes the state before it, which is the half a permissive query passes."""

    ready = request_row(world, status="eligible_for_batching")
    request_row(world)

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/eligible-for-batching").json()
    assert {i["id"] for i in body["items"]} == {str(ready)}


def test_trader_disputes_is_a_timestamp_not_a_status(world: dict[str, Any]) -> None:
    """§19.2's one accountant queue that no status can express.

    Disputing does not move a request: `status_catalog.yaml` has no disputed state, and M9 recorded
    it as `trader_disputed_at`. The seeded rows share a status deliberately — a queue built on
    status would return both or neither, and only the timestamp separates them.
    """

    disputed = request_row(world, status="eligible_for_batching")
    request_row(world, status="eligible_for_batching")
    with psycopg.connect(_psycopg(world["owner_url"])) as connection:
        connection.execute(
            "UPDATE payment_requests SET trader_disputed_at = now() WHERE id = %s", (disputed,)
        )
        connection.commit()

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/trader-disputes").json()
    assert {i["id"] for i in body["items"]} == {str(disputed)}
    assert body["total"] == 1


def test_reconciliation_tasks_excludes_other_task_types_and_finished_work(
    world: dict[str, Any],
) -> None:
    """Two exclusions, and the first is the one §19.2's wording makes easy to get wrong.

    `manual_review_task.task_type` has no value spelled `reconciliation`; the queue names the two
    discrepancy types the catalogue actually holds. A queue that returned every task would put
    privacy reviews and export-integrity work in the accountant's reconciliation list, which is the
    failure `TASK_TYPES` exists to prevent — a task filed under a name that describes something
    else is invisible to the person who filters for it.
    """

    mine = task_row(world, task_type="payment_result_discrepancy")
    incoming = task_row(world, task_type="incoming_payment_discrepancy")
    task_row(world, task_type="segment_privacy_review")
    task_row(world, task_type="payment_result_discrepancy", status="cancelled")

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/reconciliation-tasks").json()
    assert {i["id"] for i in body["items"]} == {str(mine), str(incoming)}
    assert body["total"] == 2


def test_unresolved_bundles_excludes_the_answered_and_the_still_running(
    world: dict[str, Any],
) -> None:
    """`processing` is excluded because nothing is waiting on a *person* yet.

    The two exclusions pull in opposite directions and both matter: a closed bundle is finished
    work, and a processing one is work a job still holds. A queue that included either would show
    an accountant rows they cannot act on, which is how a queue stops being read.
    """

    ready = bundle_row(world, status="ready_for_manual_review")
    partial = bundle_row(world, status="partially_matched")
    bundle_row(world, status="processing")
    bundle_row(world, status="matched")

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/unresolved-bundles-segments").json()
    assert {i["id"] for i in body["items"]} == {str(ready), str(partial)}
    assert body["total"] == 2


def test_an_export_already_carried_to_the_bank_leaves_the_send_queue(
    world: dict[str, Any],
) -> None:
    """The assertion whose absence made a negative control pass. M11 slice 3B.

    **Slice 3 blamed the wrong thing, and building the fixture is what showed it.** The commit
    said control 6 went NOT CAUGHT because no export row existed. With rows, it still would:
    `mark_sent_to_bank` sets `sent_to_bank_marked_at` *and* `status = sent_to_bank_marked` in the
    same statement (`app/commands/bank_export.py:657`), so the queue's status filter already
    excludes every sent export and the timestamp condition can never be the thing that excludes
    one. That is a sabotage which does not break the property, not a missing test.

    The condition stays — it is free, and it is the guard that would matter if a later command ever
    set one without the other. `test_marking_sent_moves_both_facts_together` is what would notice.

    What this test asserts is the reachable rule: an export already carried to the bank is not in
    the queue of exports waiting to be carried.
    """

    waiting = export_row(world, status="downloaded")
    export_row(world, status="sent_to_bank_marked", sent=True, version="second")

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/approved-exports-awaiting-send").json()
    assert {i["id"] for i in body["items"]} == {str(waiting)}
    assert body["total"] == 1


def test_marking_sent_moves_both_facts_together(world: dict[str, Any]) -> None:
    """The assumption the queue's redundant condition rests on, asserted rather than believed.

    `bank_excel_exports` has a status and a timestamp that mean the same thing, and the queue
    filters on both. That is safe only while nothing can set one without the other. Checked
    against the command rather than the schema, because it is the command that writes them.
    """

    from app.commands import bank_export

    source = inspect.getsource(bank_export.mark_sent)
    assert "export.sent_to_bank_marked_at = " in source
    assert "export.status = STATUS_SENT" in source, (
        "mark-sent no longer moves the status with the timestamp, so an export can be sent and "
        "still look unsent to a status filter — the queue's `sent_to_bank_marked_at IS NULL` "
        "condition stops being redundant and starts being load-bearing"
    )


def test_a_preview_is_never_work_somebody_can_do(world: dict[str, Any]) -> None:
    """The type condition, isolated from the status and timestamp ones.

    A preview is unsendable by construction — `bank_excel_exports` has no grant that could promote
    one — so a preview in the send queue would be a row nobody could act on.
    """

    final = export_row(world, status="validated")
    export_row(world, status="validated", export_type="preview")

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/approved-exports-awaiting-send").json()
    assert {i["id"] for i in body["items"]} == {str(final)}


def test_the_two_attempt_queues_do_not_overlap(world: dict[str, Any]) -> None:
    """§19.2 gives the accountant two attempt queues, and they answer opposite questions.

    One is money that left and has no answer yet; the other is money that came back needing a
    decision. A row in both would be work counted twice, and `superseded` must be in neither — a
    retry that replaced an attempt already carries the work.
    """

    waiting = attempt_row(world, status="sent_to_bank")
    pending = attempt_row(world, status="bank_result_pending")
    failed = attempt_row(world, status="failed")
    retry = attempt_row(world, status="retry_required")
    attempt_row(world, status="superseded")
    attempt_row(world, status="paid")

    sign_in(world, ACCOUNTANT)
    awaiting = {
        i["id"]
        for i in world["client"].get("/api/v1/queues/sent-attempts-awaiting-result").json()["items"]
    }
    decisions = {
        i["id"]
        for i in world["client"].get("/api/v1/queues/failed-partial-retry-payments").json()["items"]
    }

    assert awaiting == {str(waiting), str(pending)}
    assert decisions == {str(failed), str(retry)}
    assert awaiting & decisions == set(), "an attempt is in both queues, so it is worked twice"


def test_incoming_receipts_waits_for_a_person_not_for_a_bank(world: dict[str, Any]) -> None:
    """Two inclusions and two exclusions, and the exclusions carry the meaning.

    `duplicate_suspected` is included because the catalogue calls it a warning that "does not
    reject or confirm automatically" — it waits for a person, which is what a queue is.
    `waiting_for_bank_statement` is excluded because the thing it waits for is a bank, and
    `candidate_match` because nobody has been asked to choose yet.
    """

    review = receipt_row(world, status="needs_review")
    duplicate = receipt_row(world, status="duplicate_suspected")
    receipt_row(world, status="waiting_for_bank_statement")
    receipt_row(world, status="candidate_match")
    receipt_row(world, status="confirmed")

    sign_in(world, ACCOUNTANT)
    body = world["client"].get("/api/v1/queues/incoming-receipts-requiring-review").json()
    assert {i["id"] for i in body["items"]} == {str(review), str(duplicate)}
    assert body["total"] == 2


def test_the_manager_sees_versions_awaiting_a_decision_and_not_the_accountants_work(
    world: dict[str, Any],
) -> None:
    """M11 slice 4. The manager's queue and the accountant's slice-3 queue partition the versions.

    `draft` and `rejected` are the accountant's; `ready_for_approval` is the manager's; `approved`
    and `superseded` are nobody's. The two seeded versions in `world` are `draft` and `approved`,
    so this adds the one in between and asserts both queues at once — a version in both would be
    work two people think is theirs.
    """

    waiting = batch_version_row(world, status="ready_for_approval")

    sign_in(world, ACCOUNTANT)
    manager_queue = {
        i["id"]
        for i in world["client"]
        .get("/api/v1/queues/batch-versions-awaiting-approval")
        .json()["items"]
    }
    accountant_queue = {
        i["id"]
        for i in world["client"]
        .get("/api/v1/queues/draft-invalid-batch-versions")
        .json()["items"]
    }

    assert manager_queue == {str(waiting)}
    assert str(waiting) not in accountant_queue
    assert manager_queue & accountant_queue == set()


def test_ready_for_dispatch_is_computed_from_the_guard_not_from_a_status(
    world: dict[str, Any],
) -> None:
    """**G-2, asserted.** §19 `:1283`, and the decision recorded in `manager_and_warehouse.py`.

    No order ever sits in `ready_for_dispatch` — M10 evaluates the dispatch guard at dispatch time
    — so this queue asks the guard's own question instead: is the incoming payment confirmed.

    The seeded orders make the choice observable. An order literally in `ready_for_dispatch` is
    included in neither direction of this test, because nothing writes that status; what the queue
    must return is the `incoming_payment_confirmed` one. And
    `incoming_payment_partially_confirmed` must be **excluded** — releasing gold against part of
    the money is exactly what the guard refuses, so a queue that offered it would invite the
    mistake the guard exists to prevent.
    """

    ready = order_row(world, status="incoming_payment_confirmed")
    order_row(world, status="incoming_payment_partially_confirmed")
    order_row(world, status="waiting_for_incoming_payment")
    blocked = order_row(world, status="manager_approval_required")

    sign_in(world, UNGRANTED_ADMIN)
    body = world["client"].get("/api/v1/queues/orders-ready-for-dispatch").json()
    assert {i["id"] for i in body["items"]} == {str(ready)}
    assert body["total"] == 1

    # The blocked order is the next queue's, not this one's — an order waiting on a manager is not
    # work the warehouse can do.
    other = world["client"].get("/api/v1/queues/blocked-dispatches").json()
    assert {i["id"] for i in other["items"]} == {str(blocked)}


def test_receipt_confirmation_work_is_metal_that_left_and_was_never_acknowledged(
    world: dict[str, Any],
) -> None:
    """`dispatched` and not `delivered`, which is the trader's word rather than the centre's."""

    moving = dispatch_row(world, status="dispatched")
    dispatch_row(world, status="delivered")
    dispatch_row(world, status="pending")

    sign_in(world, UNGRANTED_ADMIN)
    body = world["client"].get("/api/v1/queues/receipt-confirmation-work").json()
    assert {i["id"] for i in body["items"]} == {str(moving)}


def test_a_technical_admin_queue_carries_no_financial_detail(world: dict[str, Any]) -> None:
    """**SEC-QUEUE-003.** §19 `:1298`'s last rule, asserted over the response body.

    "Technical admin does not receive full financial detail by default." The catalogue says it in
    the grant — `file.quarantine_review` carries `financial_content_access_is_not_implied` — and
    doc 12 `:616` says the role has "no implicit financial authority".

    **Over the body, not the query.** A redaction applied after serialisation is one a later
    serialiser change removes silently, and a test that inspected the SQL would pass against a
    response that leaked. So this reads the JSON and asserts on what a caller actually receives:
    no amount, no IBAN, no trader, no business name — searched as raw text, so a field renamed or
    nested still fails.
    """

    quarantined_file(world, filename="suspicious-receipt.pdf")

    sign_in(world, TECHNICAL_ADMIN)
    response = world["client"].get("/api/v1/queues/quarantined-files-exports")
    assert response.status_code == 200, response.text

    body = response.json()
    assert len(body["items"]) == 1
    item = body["items"][0]

    assert item["trader_id"] is None, "a technical admin was told whose business the file is"
    assert item["reference"] == "suspicious-receipt.pdf"

    # The raw payload, so a leak through a renamed or nested field fails too.
    raw = response.text
    for forbidden, what in (
        (IBANS["trader"], "an IBAN"),
        ("First Business", "a trader's name"),
        ("1000000", "an amount"),
    ):
        assert forbidden not in raw, f"the technical queue disclosed {what}"


def test_the_technical_admin_reaches_only_the_technical_queue(world: dict[str, Any]) -> None:
    """The other half: holding one technical grant is not holding the accountant's eleven.

    Without this, the redaction test above would pass just as well against a role that could read
    every financial queue in full — it only ever looks at one response.
    """

    sign_in(world, TECHNICAL_ADMIN)
    reached = {
        name
        for name in built_queue_names()
        if world["client"].get(f"/api/v1/queues/{name}").status_code == 200
    }
    assert reached == {"quarantined-files-exports"}, (
        f"the technical admin reached {sorted(reached - {'quarantined-files-exports'})}"
    )


def test_a_clean_file_is_not_quarantine_work(world: dict[str, Any]) -> None:
    """The exclusion. A queue of every file would be a file browser, not a queue."""

    flagged = quarantined_file(world, filename="flagged.pdf")
    quarantined_file(world, filename="fine.pdf", scan_status="clean")

    sign_in(world, TECHNICAL_ADMIN)
    body = world["client"].get("/api/v1/queues/quarantined-files-exports").json()
    assert {i["id"] for i in body["items"]} == {str(flagged)}


def test_every_queue_returns_the_same_five_fields(world: dict[str, Any]) -> None:
    """§19 `:1298`'s last rule, made checkable by there being one row shape.

    Swept over every built queue that has rows, and asserted by **equality** on the key set. A
    queue that grew an amount field would be a disclosure decision made once and inherited by all
    twenty-four, which is how a technical admin ends up reading financial detail in slice 5.
    """

    request_row(world)

    expected = {"id", "reference", "status", "created_at", "trader_id"}
    for name in built_queue_names():
        # Slice 4 split the surface across two roles, so the sweep signs in as whichever one owns
        # the queue. Reading every queue as one caller would silently degrade into asserting the
        # shape of 403 bodies.
        if name in ACCOUNTANT_QUEUES:
            sign_in(world, ACCOUNTANT)
        elif name in WAREHOUSE_QUEUES:
            sign_in(world, UNGRANTED_ADMIN)
        else:
            sign_in(world, TECHNICAL_ADMIN)
        body = world["client"].get(f"/api/v1/queues/{name}").json()
        assert set(body) == {"queue", "items", "next_cursor", "total"}
        for item in body["items"]:
            # `new-requests` carries two compatibility keys, and exactly one queue may. Subtracting
            # them rather than skipping the queue keeps the disclosure assertion applying to it.
            assert set(item) - {"request_number"} == expected, (
                f"{name} returned a different row shape"
            )
            if name != "new-requests":
                assert "request_number" not in item, (
                    f"{name} grew the compatibility field, which belongs to new-requests alone"
                )


def test_the_queue_returns_its_own_state_and_excludes_the_adjacent_one(
    world: dict[str, Any],
) -> None:
    """The first half passes against a query returning everything; the second is the test."""

    new = request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert {item["id"] for item in body["items"]} == {str(new)}
    assert {item["status"] for item in body["items"]} == {SUBMITTED}


def test_the_count_is_the_work_waiting_not_the_page_size(world: dict[str, Any]) -> None:
    """Rule five: permission-aware counts.

    Asserted with a `limit` **smaller than the queue**, because with a page big enough to hold
    everything `total` and `len(items)` are the same number and the test proves nothing. `total`
    must also exclude the adjacent state, or it is counting a different set than the rows.
    """

    for _ in range(5):
        request_row(world)
    request_row(world, status=UNDER_REVIEW)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE, params={"limit": 2}).json()
    assert len(body["items"]) == 2
    assert body["total"] == 5


def test_the_count_reflects_the_filter_that_was_applied(world: dict[str, Any]) -> None:
    """A count computed before the filter is a count of a different question."""

    for _ in range(3):
        request_row(world)
    request_row(world, trader="other")
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE, params={"trader_id": str(world["other_id"])}).json()
    assert body["total"] == 1
    assert {item["trader_id"] for item in body["items"]} == {str(world["other_id"])}


def test_the_page_is_bounded_even_when_the_caller_asks_for_nothing(
    world: dict[str, Any],
) -> None:
    """Rule six: no client loading of all financial records.

    The default limit is 50, so 60 rows must not come back in one page. This is the rule M5's own
    `GET /payment-requests` does not satisfy — it selects every matching row — which is recorded in
    `app/queues/payment_requests.py` and is why the queue is a new route rather than a filter on
    that one.
    """

    for _ in range(60):
        request_row(world)
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert len(body["items"]) == 50
    assert body["next_cursor"] is not None
    assert body["total"] == 60


def test_a_limit_outside_the_cap_is_refused_rather_than_clamped(world: dict[str, Any]) -> None:
    """Clamping would let a caller ask for 10,000, receive 200, and believe they had them all."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE, params={"limit": 10_000}).status_code == 400
    assert world["client"].get(QUEUE, params={"limit": 0}).status_code == 400


def test_the_walk_is_stable_when_every_row_shares_a_timestamp(world: dict[str, Any]) -> None:
    """Rules one and two together, under the only condition that can expose them.

    Six requests written at the same instant — which is what happens when a trader submits several
    in one sitting. Without `id` as the unique tiebreak, `ORDER BY created_at` leaves ties in an
    order PostgreSQL may change between executions, and the cursor then repeats or drops rows at
    the page boundary. Asserted on the **set and the count together**: a walk that returned one row
    twice and missed another has the right length and the wrong content.
    """

    stamp = datetime.now(UTC) - timedelta(hours=1)
    expected = {str(request_row(world, created_at=stamp)) for _ in range(6)}
    sign_in(world, ACCOUNTANT)

    seen: list[str] = []
    cursor: str | None = None
    for _ in range(6):
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = world["client"].get(QUEUE, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        seen.extend(item["id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert cursor is None, "the walk did not terminate"
    assert len(seen) == len(set(seen)), f"a row was returned twice across pages: {seen}"
    assert set(seen) == expected


def test_the_oldest_request_is_at_the_top(world: dict[str, Any]) -> None:
    """A work queue is drained from the bottom, unlike every other list in this project.

    Newest-first would starve the tail: the request that has waited longest would sink further with
    every new submission. This is the one place `descending=False` is correct, so it gets its own
    assertion rather than being implied by the pagination test.
    """

    base = datetime.now(UTC) - timedelta(days=1)
    oldest = request_row(world, created_at=base)
    request_row(world, created_at=base + timedelta(hours=1))
    request_row(world, created_at=base + timedelta(hours=2))
    sign_in(world, ACCOUNTANT)

    body = world["client"].get(QUEUE).json()
    assert body["items"][0]["id"] == str(oldest)


def test_a_cursor_the_api_did_not_issue_is_refused(world: dict[str, Any]) -> None:
    """An opaque token is not a number to increment, and a forged one is a 400 rather than a 500."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE, params={"cursor": "not-a-cursor"}).status_code == 400


def test_the_row_carries_only_what_triage_needs(world: dict[str, Any]) -> None:
    """§19 `:1298`'s last rule in its mildest form: a queue is not a second detail surface.

    Asserted by equality on the key set. A queue row that grew an amount field would be a
    disclosure decision made by whoever added it, and slice 5's technical-admin redaction is the
    same rule where it bites hardest.

    **This queue carries two extra keys and it is the only one that does.** Slice 2 published
    `request_number` and a non-nullable `trader_id` here; slice 3's unified row renames the first
    to `reference`, and removing the old name is a breaking change CI gate 3 refuses. The
    compatibility fields are added rather than the new ones withheld — see
    `RequestQueueRowResponse`. `test_every_queue_returns_the_same_five_fields` asserts the unified
    shape everywhere else, so this exception cannot spread without failing that.
    """

    request_row(world)
    sign_in(world, ACCOUNTANT)

    item = world["client"].get(QUEUE).json()["items"][0]
    assert set(item) == {
        "id",
        "reference",
        "status",
        "created_at",
        "trader_id",
        "request_number",
    }
    assert item["request_number"] == item["reference"], "the compatibility field has drifted"


def test_the_response_names_the_queue_it_answered(world: dict[str, Any]) -> None:
    """One envelope for twenty-four routes, so the envelope has to say which one this is."""

    request_row(world)
    sign_in(world, ACCOUNTANT)

    assert world["client"].get(QUEUE).json()["queue"] == "new-requests"


# --- The registry, which is what makes the unbuilt queues visible --------------------------


def test_every_queue_in_the_document_is_built_or_planned() -> None:
    """§19.2 names twenty-four; a queue in neither collection is one nobody decided to skip.

    This is the assertion that keeps the registry honest as slices 3 to 5 land: a forgotten queue
    is silent, and silence is what `PLANNED` exists to convert into a failure.
    """

    from app.queues.registry import BLOCKED, BUILT, PLANNED

    collections = {"BUILT": set(BUILT), "PLANNED": set(PLANNED), "BLOCKED": set(BLOCKED)}
    for first, second in (("BUILT", "PLANNED"), ("BUILT", "BLOCKED"), ("PLANNED", "BLOCKED")):
        overlap = collections[first] & collections[second]
        assert not overlap, (
            f"queues in both {first} and {second}: {sorted(overlap)}. A queue has exactly one "
            "status, and moving it between collections is a decision somebody makes deliberately."
        )

    # Twenty-four in §19.2, less `ai-status`, which the document admits "only when enabled" and no
    # AI path exists to enable. `BLOCKED` joined the sum in slice 4: three of the manager's and
    # warehouse's queues cannot be built as specified, and a registry that dropped them would
    # disagree with the document while still passing this count.
    assert len(BUILT) + len(PLANNED) + len(BLOCKED) == 23


def test_every_blocked_queue_says_what_would_unblock_it() -> None:
    """A blocked entry is a decision, and a decision with no reason is a shrug.

    `PLANNED` means a later slice does it; `BLOCKED` means no slice can until somebody decides
    something. The difference is only worth recording if the entry says *what* — otherwise the next
    person re-derives the blocker, or worse, builds the queue on a guess.
    """

    from app.queues.registry import BLOCKED

    assert BLOCKED, "the blocked collection is empty, so this gate checks nothing"
    vague = sorted(name for name, reason in BLOCKED.items() if "Unblocked by" not in reason)
    assert vague == [], f"blocked queues that do not say what would unblock them: {vague}"


def test_no_blocked_queue_is_quietly_served(world: dict[str, Any]) -> None:
    """The registry says these have no route; the route table has to agree.

    Without this, `BLOCKED` is a comment. Somebody adding one of these under a borrowed permission
    — which is precisely what its reason forbids — would leave the registry claiming it is blocked
    while the endpoint answers.
    """

    from app.queues.registry import BLOCKED

    # Asserted against the **running** application rather than a freshly built one: `create_app()`
    # with no settings needs the whole environment, and the app under test is the honest subject.
    sign_in(world, ACCOUNTANT)
    for name in BLOCKED:
        response = world["client"].get(f"/api/v1/queues/{name}")
        assert response.status_code == 404, (
            f"{name} is recorded as blocked but the route answered {response.status_code}"
        )


def test_no_queue_allowlists_a_filter_it_cannot_apply() -> None:
    """`QueueDefinition.__post_init__` refuses one at import; this proves the guard is live.

    A construction-time check nothing exercises is indistinguishable from one that was never
    written — the same reason M11 slice 1 exercised its two granted columns.
    """

    from app.db.models.payment_request import PaymentRequest
    from app.db.pagination import ListSpec, SortField
    from app.queues.contract import QueueDefinition

    with pytest.raises(ValueError, match="no column bound"):
        QueueDefinition(
            name="broken",
            permission="payment_request.read",
            spec=ListSpec(
                sorts=(SortField("id", PaymentRequest.id, unique=True),),
                filters=frozenset({"trader_id"}),
                default_sort="id",
            ),
            predicate=lambda statement, _actor: statement,
            source="test",
            filter_columns={},
        )


def test_every_built_queue_names_a_permission_the_catalogue_holds() -> None:
    """A queue guarded by a name `declare()` would refuse is a route that cannot be mounted."""

    from app.queues.registry import BUILT
    from app.security.permission_catalogue import APPROVED_PERMISSIONS

    unknown = sorted(
        definition.permission
        for definition in BUILT.values()
        if definition.permission not in APPROVED_PERMISSIONS
    )
    assert unknown == [], f"queues guarded by permissions the catalogue does not hold: {unknown}"
