from __future__ import annotations

import app.db.models  # noqa: F401  # registers every mapped table on Base.metadata
from app.db.base import Base, over_length_identifiers
from app.workers.celery_app import create_celery_app
from fastapi.testclient import TestClient

EXPECTED_TABLES = frozenset(
    {
        "admin_user_roles",
        "admin_users",
        "system_settings",
        "feature_flags",
        "retention_policies",
        "legal_holds",
        "auth_events",
        "auth_sessions",
        "recent_auth_contexts",
        "audit_logs",
        "bank_accounts",
        "bank_mappings",
        "bank_profile_versions",
        "bank_profiles",
        # The trader's payment destinations, added by 20260816_0015. One trader per
        # row and no sharing mechanism: DOC-CONFLICT-011's isolation is a fact about
        # the schema rather than a check a service performs.
        "beneficiaries",
        "center_profile",
        "file_derivations",
        "file_links",
        "file_objects",
        "idempotency_records",
        "outbox_events",
        # M5 slice 3. The aggregate and its immutable revisions. They form the
        # tree's second foreign-key cycle, on the same pattern as bank profiles
        # and versions: a request points at its current revision and every
        # revision points back at its request.
        "payment_requests",
        "payment_request_revisions",
        # M6 slice 2. Five at once, and they cannot arrive separately: three of their
        # foreign keys are composite, and a composite key needs both of its tables to
        # exist. They form the tree's **third** cycle — a batch points at its current
        # version and every version points back at its batch — plus the relation
        # `FINANCIAL_INTEGRITY_BASELINE.md:34-49` approves and no document names.
        #
        # `payment_attempts` has no `payment_batch_id` (`04_Database_Schema.md:909`):
        # membership *is* `payment_attempt_allocations`, whose uniqueness is a partial
        # unique index rather than a column, so two active versions cannot both claim
        # one attempt and the refusal comes from the database rather than a service.
        # M7 slice 1, `04_Database_Schema.md` §11.7. Append-only: the fail-closed default in
        # `020-runtime-roles.sql` gives new tables SELECT and INSERT only, so no runtime role
        # can rewrite a decision, and `20260822_0020` adds no grant.
        "batch_approvals",
        # M7 slice 2, §11.8. One table for both artifact kinds, because a preview and a final
        # export are the same rendering of the same version. `20260822_0021` likewise adds no
        # grant, which is what makes `export_type` unwritable and a preview unpromotable.
        "bank_excel_exports",
        # M8 slice 1, §12.1-12.3. The bundle's lifecycle and its three cached counts are writable
        # and its identity is not; `bank_result_bundle_files` has no UPDATE grant at all, because
        # which file sits at which position in which role are three facts that do not change. The
        # link table's only mutation is being replaced, which is how a corrected belief supersedes
        # an earlier one instead of overwriting it.
        "bank_result_bundles",
        "bank_result_bundle_files",
        "bank_result_bundle_batch_links",
        # M8 slice 2, §12.4. The smallest unit of evidence, and the table whose whole purpose is
        # that a crop can be rebuilt from its own row — which is why every provenance column is
        # outside the UPDATE grant.
        "receipt_segments",
        "payment_attempt_allocations",
        "payment_attempts",
        "payment_batch_items",
        "payment_batch_versions",
        "payment_batches",
        "permissions",
        "processing_jobs",
        "role_permissions",
        "roles",
        # The trader business, added by 20260808_0013. `trader_users` rows hang off
        # it: ownership scopes to the business, never to a login.
        "traders",
        "trader_users",
    }
)


def test_exactly_the_slice_one_tables_are_mapped() -> None:
    """Pin the mapped set, so a table cannot arrive without a decision.

    Every table here is a permanent migration and a governance commitment. An
    accidental import bringing a half-finished model into `Base.metadata` would
    otherwise reach autogenerate, and from there a migration, with nothing having
    said so out loud.
    """

    assert frozenset(Base.metadata.tables) == EXPECTED_TABLES


def test_no_identifier_would_be_silently_truncated() -> None:
    """PostgreSQL truncates at 63 bytes without warning.

    Two constraints on a wide table can collapse into the same name, and the
    second CREATE then fails — or worse, succeeds against the wrong object.
    `audit_logs` is wide enough for this to be a live risk rather than a
    theoretical one.
    """

    assert over_length_identifiers() == []


def test_celery_uses_named_utc_queues_and_no_authoritative_result_backend(
    settings_factory,
) -> None:
    settings = settings_factory(celery_task_always_eager=True)
    celery = create_celery_app(settings)

    assert celery.conf.enable_utc is True
    assert celery.conf.timezone == "UTC"
    assert celery.conf.result_backend is None
    assert celery.conf.task_ignore_result is True
    assert tuple(queue.name for queue in celery.conf.task_queues) == settings.queue_names
    assert celery.conf.task_acks_late is True
    assert celery.conf.worker_prefetch_multiplier == 1


def test_runtime_is_created_on_startup_and_closed_on_shutdown(app_factory) -> None:
    app, runtime, _settings = app_factory()

    assert not hasattr(app.state, "runtime")
    assert runtime.closed is False
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        assert app.state.accepting_traffic is True
        assert runtime.closed is False

    assert app.state.accepting_traffic is False
    assert runtime.closed is True
