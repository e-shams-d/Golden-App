"""The file lifecycle's value sets, as one Python source.

`storage_status` is the seven-value set DOC-CONFLICT-036 approved: the register's
resolution keeps `deleted` and refuses `deleted_by_policy`, because the only writer of
the second would be the policy-driven deletion ADR-005 blocks from existing. Permitting
it later is a visible widening migration, not an edit here.

`scan_status` has **no** database CHECK, and that is deliberate rather than an omission.
Enumerating the outcomes would decide DOC-CONFLICT-029 from a migration. What is enforced
instead is the consequence: `ck_file_objects_available_requires_clean_scan` is a whitelist
of the single value `clean`, so an unrecognised outcome fails closed without anyone having
to agree on the full set first.

**The reserved skip outcome is deliberately not listed here.** It has exactly one
declaring home — `app/db/models/file_object.py` — and `test_reserved_scan_status.py`
refuses every other runtime mention of it, including in a docstring. That gate is right
and this module was wrong on the first attempt: naming the value here would put it one
import away from being written, and a skip this code can produce is a skip that happens
implicitly, which is what ADR-008's interim rule forbids. A real scanner's skip stays
recordable in the column; the application simply may not invent one.
"""

from __future__ import annotations

from typing import Final

# `storage_status`, in the order the approved CHECK lists them.
PENDING: Final = "pending"
QUARANTINED: Final = "quarantined"
AVAILABLE: Final = "available"
PROCESSING_FAILED: Final = "processing_failed"
ARCHIVED: Final = "archived"
RETENTION_PENDING: Final = "retention_pending"
DELETED: Final = "deleted"

STORAGE_STATUSES: Final = (
    PENDING,
    QUARANTINED,
    AVAILABLE,
    PROCESSING_FAILED,
    ARCHIVED,
    RETENTION_PENDING,
    DELETED,
)

# `scan_status`, per `12_Security_RBAC_Audit.md:1519-1526`.
SCAN_PENDING: Final = "pending"
SCAN_CLEAN: Final = "clean"
SCAN_SUSPICIOUS: Final = "suspicious"
SCAN_FAILED: Final = "failed"

# Four of the five document 12 lists. The fifth is the reserved skip outcome, which lives
# only in the model that declares it — see the module docstring.
SCAN_STATUSES: Final = (
    SCAN_PENDING,
    SCAN_CLEAN,
    SCAN_SUSPICIOUS,
    SCAN_FAILED,
)

# The one outcome that permits availability. Named rather than inlined so the application
# guard and the database constraint are visibly the same rule.
SCAN_STATUS_PERMITTING_AVAILABILITY: Final = SCAN_CLEAN
