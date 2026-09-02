"""Every mapped table, imported here so `Base.metadata` is complete.

Alembic reads `Base.metadata` through `alembic/env.py`. A model that no module
imports is invisible to autogenerate, and the failure is silent: the revision is
generated without it and the table simply never appears. Importing them all in
one place is what keeps that from happening.
"""

from __future__ import annotations

from app.db.models.audit_log import AuditLog
from app.db.models.bank import BankAccount, BankMapping, BankProfile, BankProfileVersion
from app.db.models.bank_export import BankExcelExport
from app.db.models.bank_result_bundle import (
    BankResultBundle,
    BankResultBundleBatchLink,
    BankResultBundleFile,
)
from app.db.models.bank_statement import (
    BankStatementFile,
    BankStatementImportRun,
    BankStatementRow,
)
from app.db.models.beneficiary import Beneficiary
from app.db.models.center_profile import CenterProfile
from app.db.models.configuration import (
    FeatureFlag,
    LegalHold,
    RetentionPolicy,
    SystemSetting,
)
from app.db.models.confirmed_evidence_link import ConfirmedEvidenceLink
from app.db.models.file_object import FileDerivation, FileLink, FileObject
from app.db.models.gold_sale import GoldSaleOrder, GoldSalePricingVersion
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.identity import AdminUser, TraderUser
from app.db.models.incoming_payment import IncomingPaymentReceipt
from app.db.models.manual_review_task import ManualReviewTask
from app.db.models.matching_candidate import MatchingCandidate
from app.db.models.notification import Notification
from app.db.models.outbox_event import OutboxEvent
from app.db.models.payment_batch import (
    BatchApproval,
    PaymentAttempt,
    PaymentAttemptAllocation,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchVersion,
)
from app.db.models.payment_request import PaymentRequest, PaymentRequestRevision
from app.db.models.payment_result_publication import PaymentResultPublication
from app.db.models.processing_job import ProcessingJob
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission
from app.db.models.receipt_segment import ReceiptSegment
from app.db.models.session_and_security import AuthEvent, AuthSession, RecentAuthContext
from app.db.models.trader import Trader

__all__ = [
    "AdminUser",
    "AdminUserRole",
    "AuditLog",
    "AuthEvent",
    "AuthSession",
    "BankAccount",
    "BankExcelExport",
    "BankMapping",
    "BankProfile",
    "BankProfileVersion",
    "BankResultBundle",
    "BankResultBundleBatchLink",
    "BankResultBundleFile",
    "BankStatementFile",
    "BankStatementImportRun",
    "BankStatementRow",
    "BatchApproval",
    "Beneficiary",
    "CenterProfile",
    "ConfirmedEvidenceLink",
    "FeatureFlag",
    "FileDerivation",
    "FileLink",
    "FileObject",
    "GoldSaleOrder",
    "GoldSalePricingVersion",
    "IdempotencyRecord",
    "IncomingPaymentReceipt",
    "LegalHold",
    "ManualReviewTask",
    "MatchingCandidate",
    "Notification",
    "OutboxEvent",
    "PaymentAttempt",
    "PaymentAttemptAllocation",
    "PaymentBatch",
    "PaymentBatchItem",
    "PaymentBatchVersion",
    "PaymentRequest",
    "PaymentRequestRevision",
    "PaymentResultPublication",
    "Permission",
    "ProcessingJob",
    "ReceiptSegment",
    "RecentAuthContext",
    "RetentionPolicy",
    "Role",
    "RolePermission",
    "SystemSetting",
    "Trader",
    "TraderUser",
]
