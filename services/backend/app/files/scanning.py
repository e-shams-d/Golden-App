"""Whether a file has been scanned, and what follows from the answer.

ADR-008 — malware scanning and quarantine policy — is open. Its safe default is to
"quarantine or deny **production use** when scan status cannot satisfy the approved
policy; never treat an unchecked file as available evidence", and DOC-CONFLICT-029's
interim rule is that unknown or skipped scans fail closed.

Read literally and applied everywhere, that would mean no file can ever become
`available`, and the milestone would deliver an upload path producing nothing usable. The
resolution turns on what the safe default actually denies: **production use**, not
development use. So there are exactly two adapters and no third.

`NoScannerConfigured` is the production default. It returns `pending` for every file, and
that is not a stub — it is the honest answer to "has this been scanned" when nothing
scans. The database's one-value whitelist turns that answer into a refusal without any
application code needing to remember, which is the property worth having: the guard holds
when a future code path forgets.

`DevelopmentScanBypass` returns `clean` and **refuses to construct under
`APP_ENV=production`**, by the same pattern `app/cli/seed_demo.py` uses for the same
reason. Selecting it is an explicit configuration act and the readiness payload reports
which adapter is live, so an operator cannot be wrong about it by accident.

**There is deliberately no adapter that produces the reserved skip outcome.**
`12_Security_RBAC_Audit.md:1526` states that a skipped decision "must not be implicit. It
must reflect an approved deployment policy with compensating controls" — and no such
policy exists to reflect. Producing that value now would be the implicitness the sentence
forbids. It stays recordable, because a real scanner that skipped a file has stated a fact
worth keeping; it is simply not a fact this application may invent. The value is named in
exactly one runtime module, `app/db/models/file_object.py`, and
`test_reserved_scan_status.py` refuses it everywhere else — including in this docstring,
which is why it is described here rather than spelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

from app.files.states import (
    SCAN_CLEAN,
    SCAN_PENDING,
    SCAN_STATUS_PERMITTING_AVAILABILITY,
)

# What configuration selects. `none` is the default everywhere, including production.
POLICY_NONE: Final = "none"
POLICY_DEVELOPMENT_BYPASS: Final = "development_bypass"
POLICY_NAMES: Final = (POLICY_NONE, POLICY_DEVELOPMENT_BYPASS)


@dataclass(frozen=True)
class ScanResult:
    """One scan outcome, and whether it permits the file to be used.

    `permits_availability` is derived from the status rather than set alongside it: an
    adapter that could report "not clean, but available anyway" would be the whole hole
    this module exists to close.
    """

    status: str

    @property
    def permits_availability(self) -> bool:
        return self.status == SCAN_STATUS_PERMITTING_AVAILABILITY


class ScanPolicy(Protocol):
    """What the finalize step consults before deciding a file's state."""

    @property
    def name(self) -> str:
        """The configured name, reported in the readiness payload."""

    def scan(self, *, storage_key: str) -> ScanResult: ...


class NoScannerConfigured:
    """The production default: nothing has been scanned, and it says so."""

    name = POLICY_NONE

    def scan(self, *, storage_key: str) -> ScanResult:
        del storage_key
        return ScanResult(SCAN_PENDING)


class DevelopmentScanBypass:
    """Treats every file as clean. Refuses to exist in production."""

    name = POLICY_DEVELOPMENT_BYPASS

    def __init__(self, *, app_env: str) -> None:
        if app_env == "production":
            raise ValueError(
                "the development scan bypass cannot be used in production: it reports "
                "every file as clean without scanning it, and ADR-008's safe default is "
                "to deny production use when scan status cannot satisfy the approved "
                "policy. Configure a real scanner or leave FILE_SCAN_POLICY unset."
            )
        self._app_env = app_env

    def scan(self, *, storage_key: str) -> ScanResult:
        del storage_key
        return ScanResult(SCAN_CLEAN)


def build_scan_policy(*, policy_name: str, app_env: str) -> ScanPolicy:
    """Select the adapter, refusing anything not named.

    An unknown name is a refusal rather than a fallback to the permissive adapter — and
    rather than a fallback to the safe one, because a typo that silently selects *any*
    policy is a deployment that is not running the policy it was configured with.
    """

    if policy_name == POLICY_NONE:
        return NoScannerConfigured()
    if policy_name == POLICY_DEVELOPMENT_BYPASS:
        return DevelopmentScanBypass(app_env=app_env)
    raise ValueError(
        f"unknown scan policy {policy_name!r}; the approved names are "
        f"{', '.join(POLICY_NAMES)}"
    )
