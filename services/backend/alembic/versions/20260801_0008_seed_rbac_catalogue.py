"""Seed the approved roles, permissions and default grants.

The data below is generated from `docs/governance/permission_catalog.yaml` by
`scripts/rbac_catalogue.py` and inlined here, because `docs/` is not copied into
the container image and a migration that read it would fail on every deployment.
`tests/backend/test_rbac_seed_matches_catalogue.py` compares the two, so a change
to governance that does not reach this file fails CI rather than leaving a
permission that exists in one place and not the other.

Only canonical identifiers are seeded. Doc 05's API spellings are deprecated
aliases under DOC-CONFLICT-013 and are deliberately absent: seeding one would
make the wrong identifier grantable, and `payment_batch.approve` names a mutable
container where `payment_batch_version.approve` names the exact version that was
reviewed.

`audit.export` and `break_glass.*` are seeded with zero grants. Break-glass is
disabled for Phase 1A including the flag itself (POL-005), so the rows exist for
catalogue completeness and there is no activation path.

Idempotent: every insert is ON CONFLICT DO NOTHING, because the migrate container
runs on every stack start and a second run must neither fail nor duplicate.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0008"
down_revision: str | None = "20260801_0007"
branch_labels: str | None = None
depends_on: str | None = None


# Generated from docs/governance/permission_catalog.yaml by
# scripts/rbac_catalogue.py. Compared against that file by
# tests/backend/test_rbac_seed_matches_catalogue.py, so drift fails CI.
ROLES: tuple[tuple[str, str, bool, bool], ...] = (
    (
        "trader_owner",
        "own trader records, requests, publications, acknowledgements, and disputes",
        False,
        True,
    ),
    (
        "accountant",
        "operational review, batching, bank results, evidence, and confirmation",
        False,
        True,
    ),
    ("manager", "exact batch-version approval and configured high-risk decisions", False, True),
    ("warehouse_operator", "dispatch and receipt operations only", False, True),
    (
        "business_admin",
        "user/trader administration and approved business configuration",
        False,
        True,
    ),
    (
        "technical_admin",
        "technical configuration and operational support without implicit financial authority",
        False,
        True,
    ),
    ("read_only_auditor", "masked read-only records, reports, and audit", False, True),
    (
        "support_operator",
        "optional limited support workflow without financial mutation",
        False,
        False,
    ),
    ("system_worker", "technical asynchronous work without human financial authority", True, True),
)

PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("auth.session.read_own", "identity_access"),
    ("auth.session.revoke_own", "identity_access"),
    ("auth.session.read_all", "identity_access"),
    ("auth.session.revoke_all", "identity_access"),
    ("user.read", "identity_access"),
    ("user.create", "identity_access"),
    ("user.update", "identity_access"),
    ("user.deactivate", "identity_access"),
    ("role.read", "identity_access"),
    ("role.manage", "identity_access"),
    ("permission.read", "identity_access"),
    ("break_glass.activate", "identity_access"),
    ("break_glass.review", "identity_access"),
    ("trader.read", "trader_beneficiary"),
    ("trader.create", "trader_beneficiary"),
    ("trader.approve", "trader_beneficiary"),
    ("trader.reject", "trader_beneficiary"),
    ("trader.suspend", "trader_beneficiary"),
    ("trader.reactivate", "trader_beneficiary"),
    ("trader.update_business", "trader_beneficiary"),
    ("beneficiary.read", "trader_beneficiary"),
    ("beneficiary.create", "trader_beneficiary"),
    ("beneficiary.create_own", "trader_beneficiary"),
    ("beneficiary.update_future", "trader_beneficiary"),
    ("beneficiary.deactivate", "trader_beneficiary"),
    ("gold_sale.read", "gold_incoming_payment"),
    ("gold_sale.create_own", "gold_incoming_payment"),
    ("gold_sale.review", "gold_incoming_payment"),
    ("gold_sale.price", "gold_incoming_payment"),
    ("gold_sale.cancel", "gold_incoming_payment"),
    ("gold_sale.dispatch", "gold_incoming_payment"),
    ("incoming_receipt.create_own", "gold_incoming_payment"),
    ("incoming_receipt.read", "gold_incoming_payment"),
    ("incoming_payment.match", "gold_incoming_payment"),
    ("incoming_payment.confirm", "gold_incoming_payment"),
    ("incoming_payment.correct", "gold_incoming_payment"),
    ("bank_statement.upload", "gold_incoming_payment"),
    ("bank_statement.import", "gold_incoming_payment"),
    ("bank_statement.read", "gold_incoming_payment"),
    ("payment_request.create_own", "outgoing_payment_request"),
    ("payment_request.read_own", "outgoing_payment_request"),
    ("payment_request.read", "outgoing_payment_request"),
    ("payment_request.create_internal", "outgoing_payment_request"),
    ("payment_request.create_revision_own", "outgoing_payment_request"),
    ("payment_request.create_revision_internal", "outgoing_payment_request"),
    ("payment_request.submit", "outgoing_payment_request"),
    ("payment_request.review", "outgoing_payment_request"),
    ("payment_request.request_correction", "outgoing_payment_request"),
    ("payment_request.mark_eligible", "outgoing_payment_request"),
    ("payment_request.cancel", "outgoing_payment_request"),
    ("payment_batch.read", "batch_approval_export"),
    ("payment_batch.create", "batch_approval_export"),
    ("payment_batch.cancel_draft", "batch_approval_export"),
    ("payment_batch_version.create", "batch_approval_export"),
    ("payment_batch_version.finalize", "batch_approval_export"),
    ("payment_batch_version.read_approval_view", "batch_approval_export"),
    ("payment_batch_version.approve", "batch_approval_export"),
    ("payment_batch_version.reject", "batch_approval_export"),
    ("payment_batch_version.invalidate_approval", "batch_approval_export"),
    ("bank_export.generate_preview", "batch_approval_export"),
    ("bank_export.generate_final", "batch_approval_export"),
    ("bank_export.read", "batch_approval_export"),
    ("bank_export.download", "batch_approval_export"),
    ("bank_export.mark_sent", "batch_approval_export"),
    ("bank_export.quarantine", "batch_approval_export"),
    ("bank_result_bundle.upload", "results_evidence_publication"),
    ("bank_result_bundle.read", "results_evidence_publication"),
    ("bank_result_bundle.link_batch", "results_evidence_publication"),
    ("bank_result_bundle.close", "results_evidence_publication"),
    ("receipt_segment.create_external", "results_evidence_publication"),
    ("receipt_segment.create_crop", "results_evidence_publication"),
    ("receipt_segment.read", "results_evidence_publication"),
    ("matching_candidate.create", "results_evidence_publication"),
    ("matching_candidate.review", "results_evidence_publication"),
    ("evidence_link.confirm", "results_evidence_publication"),
    ("evidence_link.replace", "results_evidence_publication"),
    ("evidence_link.revoke", "results_evidence_publication"),
    ("payment_attempt.read", "results_evidence_publication"),
    ("payment_attempt.confirm_paid", "results_evidence_publication"),
    ("payment_attempt.confirm_failed", "results_evidence_publication"),
    ("payment_attempt.create_retry", "results_evidence_publication"),
    ("payment_attempt.correct_result", "results_evidence_publication"),
    ("payment_publication.preview", "results_evidence_publication"),
    ("payment_publication.publish", "results_evidence_publication"),
    ("payment_publication.correct", "results_evidence_publication"),
    ("payment_publication.read_own", "results_evidence_publication"),
    ("payment_publication.acknowledge_own", "results_evidence_publication"),
    ("payment_publication.dispute_own", "results_evidence_publication"),
    ("file.upload", "files_operations"),
    ("file.read_metadata", "files_operations"),
    ("file.preview", "files_operations"),
    ("file.download", "files_operations"),
    ("file.download_bank_export", "files_operations"),
    ("file.read_sensitive_bundle", "files_operations"),
    ("file.quarantine_review", "files_operations"),
    ("manual_review.read", "files_operations"),
    ("manual_review.assign", "files_operations"),
    ("manual_review.resolve", "files_operations"),
    ("report.read", "files_operations"),
    ("report.export", "files_operations"),
    ("audit.read", "files_operations"),
    ("audit.export", "files_operations"),
    ("security_event.read", "files_operations"),
    ("bank_profile.read", "configuration_governance"),
    ("bank_profile.create_version", "configuration_governance"),
    ("bank_mapping.create_version", "configuration_governance"),
    ("source_bank_account.manage", "configuration_governance"),
    ("feature_flag.read", "configuration_governance"),
    ("feature_flag.update", "configuration_governance"),
    ("ai_configuration.read", "configuration_governance"),
    ("ai_configuration.update", "configuration_governance"),
    ("retention.read", "configuration_governance"),
    ("retention.propose", "configuration_governance"),
    ("retention.approve", "configuration_governance"),
    ("retention.activate", "configuration_governance"),
    ("legal_hold.read", "configuration_governance"),
    ("legal_hold.manage", "configuration_governance"),
    ("backup_status.read", "configuration_governance"),
)

# (role_code, permission_code) pairs the catalogue grants by default.
ROLE_PERMISSIONS: tuple[tuple[str, str], ...] = (
    ("accountant", "audit.read"),
    ("accountant", "auth.session.read_own"),
    ("accountant", "auth.session.revoke_own"),
    ("accountant", "bank_export.download"),
    ("accountant", "bank_export.generate_final"),
    ("accountant", "bank_export.generate_preview"),
    ("accountant", "bank_export.mark_sent"),
    ("accountant", "bank_export.read"),
    ("accountant", "bank_profile.read"),
    ("accountant", "bank_result_bundle.close"),
    ("accountant", "bank_result_bundle.link_batch"),
    ("accountant", "bank_result_bundle.read"),
    ("accountant", "bank_result_bundle.upload"),
    ("accountant", "bank_statement.import"),
    ("accountant", "bank_statement.read"),
    ("accountant", "bank_statement.upload"),
    ("accountant", "beneficiary.create"),
    ("accountant", "beneficiary.deactivate"),
    ("accountant", "beneficiary.read"),
    ("accountant", "beneficiary.update_future"),
    ("accountant", "evidence_link.confirm"),
    ("accountant", "evidence_link.replace"),
    ("accountant", "evidence_link.revoke"),
    ("accountant", "file.download"),
    ("accountant", "file.download_bank_export"),
    ("accountant", "file.preview"),
    ("accountant", "file.read_metadata"),
    ("accountant", "file.read_sensitive_bundle"),
    ("accountant", "file.upload"),
    ("accountant", "gold_sale.cancel"),
    ("accountant", "gold_sale.price"),
    ("accountant", "gold_sale.read"),
    ("accountant", "gold_sale.review"),
    ("accountant", "incoming_payment.confirm"),
    ("accountant", "incoming_payment.correct"),
    ("accountant", "incoming_payment.match"),
    ("accountant", "incoming_receipt.read"),
    ("accountant", "manual_review.assign"),
    ("accountant", "manual_review.read"),
    ("accountant", "manual_review.resolve"),
    ("accountant", "matching_candidate.create"),
    ("accountant", "matching_candidate.review"),
    ("accountant", "payment_attempt.confirm_failed"),
    ("accountant", "payment_attempt.confirm_paid"),
    ("accountant", "payment_attempt.create_retry"),
    ("accountant", "payment_attempt.read"),
    ("accountant", "payment_batch.cancel_draft"),
    ("accountant", "payment_batch.create"),
    ("accountant", "payment_batch.read"),
    ("accountant", "payment_batch_version.create"),
    ("accountant", "payment_batch_version.finalize"),
    ("accountant", "payment_batch_version.read_approval_view"),
    ("accountant", "payment_publication.preview"),
    ("accountant", "payment_publication.publish"),
    ("accountant", "payment_request.cancel"),
    ("accountant", "payment_request.create_internal"),
    ("accountant", "payment_request.create_revision_internal"),
    ("accountant", "payment_request.mark_eligible"),
    ("accountant", "payment_request.read"),
    ("accountant", "payment_request.request_correction"),
    ("accountant", "payment_request.review"),
    ("accountant", "receipt_segment.create_crop"),
    ("accountant", "receipt_segment.create_external"),
    ("accountant", "receipt_segment.read"),
    ("accountant", "report.read"),
    ("accountant", "trader.read"),
    ("business_admin", "ai_configuration.read"),
    ("business_admin", "audit.read"),
    ("business_admin", "auth.session.read_all"),
    ("business_admin", "auth.session.read_own"),
    ("business_admin", "auth.session.revoke_all"),
    ("business_admin", "auth.session.revoke_own"),
    ("business_admin", "bank_profile.create_version"),
    ("business_admin", "bank_profile.read"),
    ("business_admin", "beneficiary.deactivate"),
    ("business_admin", "beneficiary.read"),
    ("business_admin", "feature_flag.read"),
    ("business_admin", "legal_hold.read"),
    ("business_admin", "payment_batch.read"),
    ("business_admin", "payment_request.read"),
    ("business_admin", "permission.read"),
    ("business_admin", "report.read"),
    ("business_admin", "retention.propose"),
    ("business_admin", "retention.read"),
    ("business_admin", "role.manage"),
    ("business_admin", "role.read"),
    ("business_admin", "source_bank_account.manage"),
    ("business_admin", "trader.approve"),
    ("business_admin", "trader.create"),
    ("business_admin", "trader.reactivate"),
    ("business_admin", "trader.read"),
    ("business_admin", "trader.reject"),
    ("business_admin", "trader.suspend"),
    ("business_admin", "trader.update_business"),
    ("business_admin", "user.create"),
    ("business_admin", "user.deactivate"),
    ("business_admin", "user.read"),
    ("business_admin", "user.update"),
    ("manager", "audit.read"),
    ("manager", "auth.session.read_own"),
    ("manager", "auth.session.revoke_own"),
    ("manager", "bank_export.read"),
    ("manager", "bank_profile.read"),
    ("manager", "bank_result_bundle.read"),
    ("manager", "bank_statement.read"),
    ("manager", "beneficiary.deactivate"),
    ("manager", "beneficiary.read"),
    ("manager", "feature_flag.read"),
    ("manager", "file.preview"),
    ("manager", "file.read_metadata"),
    ("manager", "file.read_sensitive_bundle"),
    ("manager", "gold_sale.read"),
    ("manager", "incoming_receipt.read"),
    ("manager", "legal_hold.read"),
    ("manager", "manual_review.read"),
    ("manager", "payment_attempt.read"),
    ("manager", "payment_batch.read"),
    ("manager", "payment_batch_version.approve"),
    ("manager", "payment_batch_version.invalidate_approval"),
    ("manager", "payment_batch_version.read_approval_view"),
    ("manager", "payment_batch_version.reject"),
    ("manager", "payment_request.read"),
    ("manager", "permission.read"),
    ("manager", "receipt_segment.read"),
    ("manager", "report.read"),
    ("manager", "retention.read"),
    ("manager", "role.read"),
    ("manager", "trader.approve"),
    ("manager", "trader.reactivate"),
    ("manager", "trader.read"),
    ("manager", "trader.reject"),
    ("manager", "trader.suspend"),
    ("read_only_auditor", "audit.read"),
    ("read_only_auditor", "auth.session.read_own"),
    ("read_only_auditor", "auth.session.revoke_own"),
    ("read_only_auditor", "backup_status.read"),
    ("read_only_auditor", "bank_export.read"),
    ("read_only_auditor", "bank_profile.read"),
    ("read_only_auditor", "beneficiary.read"),
    ("read_only_auditor", "feature_flag.read"),
    ("read_only_auditor", "file.read_metadata"),
    ("read_only_auditor", "gold_sale.read"),
    ("read_only_auditor", "incoming_receipt.read"),
    ("read_only_auditor", "legal_hold.read"),
    ("read_only_auditor", "payment_attempt.read"),
    ("read_only_auditor", "payment_batch.read"),
    ("read_only_auditor", "payment_batch_version.read_approval_view"),
    ("read_only_auditor", "payment_request.read"),
    ("read_only_auditor", "permission.read"),
    ("read_only_auditor", "report.read"),
    ("read_only_auditor", "retention.read"),
    ("read_only_auditor", "role.read"),
    ("read_only_auditor", "security_event.read"),
    ("read_only_auditor", "trader.read"),
    ("support_operator", "auth.session.read_own"),
    ("support_operator", "auth.session.revoke_own"),
    ("system_worker", "matching_candidate.create"),
    ("technical_admin", "ai_configuration.read"),
    ("technical_admin", "auth.session.read_own"),
    ("technical_admin", "auth.session.revoke_own"),
    ("technical_admin", "backup_status.read"),
    ("technical_admin", "bank_mapping.create_version"),
    ("technical_admin", "bank_profile.read"),
    ("technical_admin", "feature_flag.read"),
    ("technical_admin", "feature_flag.update"),
    ("technical_admin", "file.quarantine_review"),
    ("technical_admin", "file.read_metadata"),
    ("technical_admin", "security_event.read"),
    ("trader_owner", "auth.session.read_own"),
    ("trader_owner", "auth.session.revoke_own"),
    ("trader_owner", "beneficiary.create_own"),
    ("trader_owner", "beneficiary.read"),
    ("trader_owner", "beneficiary.update_future"),
    ("trader_owner", "file.download"),
    ("trader_owner", "file.preview"),
    ("trader_owner", "file.read_metadata"),
    ("trader_owner", "file.upload"),
    ("trader_owner", "gold_sale.create_own"),
    ("trader_owner", "gold_sale.read"),
    ("trader_owner", "incoming_receipt.create_own"),
    ("trader_owner", "payment_publication.acknowledge_own"),
    ("trader_owner", "payment_publication.dispute_own"),
    ("trader_owner", "payment_publication.read_own"),
    ("trader_owner", "payment_request.cancel"),
    ("trader_owner", "payment_request.create_own"),
    ("trader_owner", "payment_request.create_revision_own"),
    ("trader_owner", "payment_request.read_own"),
    ("trader_owner", "payment_request.submit"),
    ("trader_owner", "trader.read"),
    ("warehouse_operator", "auth.session.read_own"),
    ("warehouse_operator", "auth.session.revoke_own"),
    ("warehouse_operator", "file.download"),
    ("warehouse_operator", "file.preview"),
    ("warehouse_operator", "file.read_metadata"),
    ("warehouse_operator", "file.upload"),
    ("warehouse_operator", "gold_sale.dispatch"),
    ("warehouse_operator", "gold_sale.read"),
)


def upgrade() -> None:
    bind = op.get_bind()

    for code, description, is_system, is_enabled in ROLES:
        bind.execute(
            sa.text(
                "INSERT INTO roles (code, description, is_system, is_enabled) "
                "VALUES (:code, :description, :is_system, :is_enabled) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {
                "code": code,
                "description": description,
                "is_system": is_system,
                "is_enabled": is_enabled,
            },
        )

    for code, domain in PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, domain) VALUES (:code, :domain) "
                "ON CONFLICT (code) DO NOTHING"
            ),
            {"code": code, "domain": domain},
        )

    for role_code, permission_code in ROLE_PERMISSIONS:
        # Joined by code rather than by a generated id, so the statement reads as
        # what it means and does not depend on the insertion order above.
        bind.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.code = :role_code AND p.code = :permission_code "
                "ON CONFLICT DO NOTHING"
            ),
            {"role_code": role_code, "permission_code": permission_code},
        )


def downgrade() -> None:
    """Remove the seeded grants, and nothing else.

    Roles and permissions stay: an operator may have granted a seeded role to a
    real admin, and dropping the role would cascade that grant away. Removing the
    default pairs is reversible; removing the roles is not.
    """

    bind = op.get_bind()
    for role_code, permission_code in ROLE_PERMISSIONS:
        bind.execute(
            sa.text(
                "DELETE FROM role_permissions rp USING roles r, permissions p "
                "WHERE rp.role_id = r.id AND rp.permission_id = p.id "
                "AND r.code = :role_code AND p.code = :permission_code"
            ),
            {"role_code": role_code, "permission_code": permission_code},
        )
