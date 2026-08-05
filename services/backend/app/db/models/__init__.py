"""Every mapped table, imported here so `Base.metadata` is complete.

Alembic reads `Base.metadata` through `alembic/env.py`. A model that no module
imports is invisible to autogenerate, and the failure is silent: the revision is
generated without it and the table simply never appears. Importing them all in
one place is what keeps that from happening.
"""

from __future__ import annotations

from app.db.models.audit_log import AuditLog
from app.db.models.center_profile import CenterProfile
from app.db.models.idempotency_record import IdempotencyRecord
from app.db.models.identity import AdminUser, TraderUser
from app.db.models.outbox_event import OutboxEvent
from app.db.models.processing_job import ProcessingJob
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission
from app.db.models.session_and_security import AuthEvent, AuthSession, RecentAuthContext

__all__ = [
    "AdminUser",
    "AdminUserRole",
    "AuditLog",
    "AuthEvent",
    "AuthSession",
    "CenterProfile",
    "IdempotencyRecord",
    "OutboxEvent",
    "Permission",
    "ProcessingJob",
    "RecentAuthContext",
    "Role",
    "RolePermission",
    "TraderUser",
]
