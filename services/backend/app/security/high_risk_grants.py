"""Which permission grants doc 12:642 requires an alert for — one derived artifact.

`12_Security_RBAC_Audit.md:642` lists what a role change must produce, and its last item
is *"alerting for grants of manager approval, role management, audit export, retention
approval, or break-glass capability."* That sentence names **five** capabilities in
English and no permission codes at all. Turning it into something a command can check is
the whole job of this module, and it is deliberately one place rather than a literal list
inside the command: a phrase-to-code mapping scattered across call sites is a mapping that
silently disagrees with itself.

**Five, not four.** The M3 plan's slice-8E section names four and omits break-glass. The
document names five. The document wins, and the fifth is treated differently — see below —
which is why the plan's count was worth checking rather than copying.

**Break-glass is refused, not alerted, and that is stronger.** `permission_catalog.yaml`
records `break_glass.activate` with `default_roles: []`,
`assignment: disabled_for_phase_1a` and `availability: disabled_by_approved_POL_005`, and
the constraint entry says in terms: *"disabled for Phase 1A by approved POL-005; no
endpoint, grant, feature flag, runtime activation, or financial bypass; future enablement
requires a new explicit decision."* A grant of it is therefore not a high-risk act to be
recorded — it is an act the approved policy forbids. Alerting on something that must not
happen, while allowing it to happen, would be the weaker of the two available readings,
and the alert would be the only trace of a capability POL-005 says cannot exist.

So this module answers two questions rather than one: which grants are refused outright,
and which are permitted but must produce an alert row.

**Every code here is checked against the catalogue** by `test_high_risk_grants.py`, using
the catalogue file this module did not write. A mapping that named a permission the
platform does not have would read as coverage while alerting on nothing — the failure mode
this file is most exposed to, because the codes are strings chosen by a human reading
English prose.

Covers: SEC-HIGHRISK-001.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

# The document's phrases, in its order, each resolved to the catalogue codes that carry
# that capability. Keyed by the phrase rather than by the code so a reader can check the
# derivation against `:642` without knowing the permission model — and so that a capability
# gaining a second code is an edit to one entry rather than an addition nobody can trace.
ALERTABLE_GRANTS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        # "manager approval" — the approval of an outgoing payment batch version, which is
        # the only manager-approval act Phase 1A has. `payment_batch.approve` is document
        # 05's spelling and the catalogue's `naming_note` rejects it: it names the mutable
        # container and would let an approval outlive the content it approved.
        "manager approval": ("payment_batch_version.approve",),
        # "role management" — the permission this very route requires. Granting somebody
        # the ability to grant is the escalation every other entry here depends on.
        "role management": ("role.manage",),
        # "audit export" — `audit.read` is deliberately **not** here. The document says
        # export, and reading a masked audit record is a routine auditor activity that
        # three seeded roles hold; conflating them would make the alert fire constantly
        # and teach its reader to ignore it.
        "audit export": ("audit.export",),
        # "retention approval" — again the approval, not the proposal or the read.
        # `retention.propose` is the half of the pair that cannot act alone, and the
        # catalogue's `retention_governance` entry requires that technical_admin cannot
        # unilaterally shorten retention *and* execute deletion.
        "retention approval": ("retention.approve",),
    }
)

# The fifth capability, and the one that is refused rather than recorded.
#
# `break_glass.review` is **not** here: it is a read-only masked review capability with
# `assignment: explicitly_appointed_security_or_governance_reviewer`, which is an
# appointment the policy contemplates. It is `break_glass.activate` — the bypass itself —
# that POL-005 disables.
FORBIDDEN_GRANTS: frozenset[str] = frozenset({"break_glass.activate"})

FORBIDDEN_REASON = (
    "break_glass.activate cannot be granted: permission_catalog.yaml records it as "
    "disabled_by_approved_POL_005 for Phase 1A, with no grant, feature flag or runtime "
    "activation. Enabling it requires a new explicit owner decision, not a role edit."
)


def alertable_codes() -> frozenset[str]:
    """Every permission code whose grant must produce an alert row."""

    return frozenset(code for codes in ALERTABLE_GRANTS.values() for code in codes)


def capability_for(code: str) -> str | None:
    """The document's phrase this code belongs to, or `None` if it is an ordinary grant.

    Returned so the alert row can name the capability in the words `:642` uses. An alert
    that said only `retention.approve` would make its reader do the derivation again, at
    the worst possible moment.
    """

    for capability, codes in ALERTABLE_GRANTS.items():
        if code in codes:
            return capability
    return None


def classify(granted: frozenset[str]) -> tuple[frozenset[str], dict[str, str]]:
    """Split newly-granted codes into the forbidden and the alertable.

    Takes what is being **added**, not the whole resulting set: re-saving a role that
    already holds `role.manage` grants nothing and must not alert. An alert that fires on
    an unchanged permission set is one an operator learns to dismiss, and the one that
    matters then arrives in a stream of noise.
    """

    forbidden = granted & FORBIDDEN_GRANTS
    alertable = {
        code: capability
        for code in sorted(granted)
        if (capability := capability_for(code)) is not None
    }
    return forbidden, alertable
