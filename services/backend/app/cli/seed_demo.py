"""Populate a demonstration deployment with a plausible amount of work.

A demonstration where every list holds one row reads as a prototype, whatever the code
behind it does. The approval screen with a single pending business cannot show what
approving *is* — there is nothing to choose between, nothing already decided to compare it
against, and no suspended account to explain why suspension is a separate axis from
approval. This command creates enough of each that the screens mean something.

**Through the command layer, never through SQL.** Every trader here is created by
`trader_lifecycle.register_trader` and every decision by `trader_lifecycle.decide`, the same
functions the HTTP routes call. So the seeded data satisfies every invariant the platform
enforces — record versions, audit rows, the primary-contact uniqueness index, the status
CHECKs — and a demonstration is never showing rows the application itself could not have
produced. Writing them with `INSERT` would be faster and would seed a database the code
disagrees with.

**It refuses to run in production, and refuses to run twice.** The first guard is
`app_env`; the second is a count, taken inside the transaction, of the traders it would
create. Neither is a formality: this command writes credentials it prints to the terminal,
which is exactly the thing `12_Security_RBAC_Audit.md:386` forbids anywhere near a
production image — and running it twice would produce a second set of businesses with the
same names, which reads as a bug during the demonstration it exists to support.

**The credentials are printed and not stored.** They are generated here, shown once, and
never written to a file: a seeded password in a file is a seeded password in a backup. The
operator copies them for the demonstration and they die with the deployment.

This is not part of any verification gate. `verify-native.sh` decides whether the
repository is sound; this decides whether a person can be shown the platform, which is a
different question — the same division `infra/scripts/rehearse-demo.sh` records.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.redaction import RedactionPolicy
from app.audit.registry import APPROVE_TRADER, REJECT_TRADER, SUSPEND_TRADER
from app.audit.writer import AuditActor, AuditContext
from app.commands import trader_lifecycle
from app.commands.admin_user_lifecycle import NewAdminUser, create_admin_user
from app.core.config import Settings
from app.core.runtime import RuntimeServices
from app.core.time import utc_now
from app.db.models.identity import AdminUser
from app.db.models.trader import Trader
from app.db.unit_of_work import SqlAlchemyUnitOfWork
from app.security.passwords import Argon2Parameters

SEED_REDACTION = RedactionPolicy(mask_iban=True)

REFUSED_IN_PRODUCTION = 2
ALREADY_SEEDED = 3

# The actor every seeded write is attributed to. `system_maintenance` with no id, for the
# reason `create_first_admin` records: the audit table requires a human action to identify
# its actor, and inventing a placeholder person would make these rows indistinguishable
# from real attributed ones. A demonstration whose audit trail claims a human approved
# these businesses is a demonstration that lies in the one table nobody may edit.
SEED_ACTOR = AuditActor(actor_type="system_maintenance")


@dataclass(frozen=True, slots=True)
class Business:
    display_name: str
    contact_name: str
    phone: str
    # What the centre has decided about it, or None for a business still waiting. The
    # pending ones are the point: an approval screen needs something to approve.
    decision: str | None = None
    reason: str | None = None


# Nine businesses, chosen so every state on the approval screen and the trader's own
# account screen is visible at once, and so the pending queue has more than one row —
# a queue of one cannot show an operator choosing.
BUSINESSES: tuple[Business, ...] = (
    Business("طلا و جواهر رضوی", "سید مهدی رضوی", "09121110001"),
    Business("زرگری کریمی", "حسین کریمی", "09121110002"),
    Business("طلافروشی آیریک", "نگار آیریک", "09121110003"),
    Business("گالری طلای پارسیان", "بابک پارسا", "09121110004", "approve"),
    Business("طلا و سکه اصفهانی", "مریم اصفهانی", "09121110005", "approve"),
    Business("زرین‌گستر البرز", "کاوه نیکنام", "09121110006", "approve"),
    Business(
        "طلافروشی نامشخص",
        "فرهاد بی‌نام",
        "09121110007",
        "reject",
        "مدارک هویتی ارائه‌شده با نام کسب‌وکار مطابقت ندارد",
    ),
    Business(
        "زرگری شهاب",
        "شهاب مرادی",
        "09121110008",
        "suspend",
        "بررسی گزارش تخلف تا اعلام نتیجه",
    ),
    Business("طلای نگین کویر", "سمیرا نگین", "09121110009", "approve"),
)


@dataclass(frozen=True, slots=True)
class Colleague:
    username: str
    full_name: str
    role: str


# Three staff accounts across the roles whose navigation actually differs, so the
# role-aware menu can be demonstrated by signing in as two people rather than described.
COLLEAGUES: tuple[Colleague, ...] = (
    Colleague("hesabdar", "زهرا حسابدار", "accountant"),
    Colleague("modir", "علی مدیر", "manager"),
    Colleague("naghsh_khan", "رضا بازرس", "read_only_auditor"),
)


class SeedRefused(RuntimeError):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def _password() -> str:
    """A distinct credential per seeded identity, printed once and never stored.

    Random rather than a shared literal: a demonstration deployment reachable on a network
    with one known password for nine accounts is a demonstration deployment somebody else
    can sign into.
    """

    return f"Demo-{secrets.token_urlsafe(9)}"


def _refuse_if_unsafe(session: Session, settings: Settings) -> None:
    if settings.app_env == "production":
        raise SeedRefused(
            "this command generates credentials and prints them to the terminal, which "
            "12_Security_RBAC_Audit.md:386 forbids anywhere near a production deployment. "
            "It will not run with APP_ENV=production.",
            REFUSED_IN_PRODUCTION,
        )

    existing = session.scalar(select(func.count()).select_from(Trader)) or 0
    if existing:
        raise SeedRefused(
            f"the deployment already has {existing} business(es). Seeding again would "
            "create a second set with the same names, which looks like a defect during "
            "the demonstration this exists to support. Start from an empty database — "
            "infra/scripts/rehearse-demo.sh does that for you.",
            ALREADY_SEEDED,
        )


def _decider(session: Session) -> AdminUser:
    """The account whose decisions these are.

    Required rather than optional: `trader_lifecycle.decide` writes an audit row for every
    approval, and a decision with no administrator behind it is a row an auditor cannot
    follow. The bootstrap account is the only one that exists before this runs.
    """

    admin = session.scalars(select(AdminUser).order_by(AdminUser.created_at)).first()
    if admin is None:
        raise SeedRefused(
            "no staff account exists. Run `python -m app.cli.create_first_admin` first — "
            "the decisions this command seeds have to be attributable to somebody.",
            ALREADY_SEEDED,
        )
    return admin


def seed(
    uow: SqlAlchemyUnitOfWork,
    *,
    settings: Settings,
    parameters: Argon2Parameters,
    now: datetime,
) -> list[tuple[str, str, str]]:
    """Create the businesses, their decisions and the staff accounts. Returns credentials.

    The caller commits. One transaction, because a half-seeded deployment is worse than an
    empty one: the demonstration would open on a screen whose contents nobody can explain.
    """

    # The unit of work rather than a bare session, because  claims one
    # through  and an adapter that satisfied only the attribute access
    # would be this file lying to the type checker about the thing it claims most loudly:
    # that these rows go through the same commands the routes do.
    session = uow.session
    _refuse_if_unsafe(session, settings)
    decider = _decider(session)
    context = AuditContext(request_id=None)
    credentials: list[tuple[str, str, str]] = []

    names = {
        "approve": APPROVE_TRADER,
        "reject": REJECT_TRADER,
        "suspend": SUSPEND_TRADER,
    }

    for business in BUSINESSES:
        password = _password()
        trader_lifecycle.register_trader(
            trader_lifecycle.RegisterTrader(
                display_name=business.display_name,
                primary_phone=business.phone,
                contact_full_name=business.contact_name,
                password=password,
            ),
            session=session,
            policy=SEED_REDACTION,
            parameters=parameters,
            password_max_length=settings.password_max_length,
            actor=SEED_ACTOR,
            context=context,
            now=now,
        )
        session.flush()
        credentials.append(("trader", business.phone, password))

        if business.decision is None:
            continue

        # Read back the row the command just created, so the decision carries the record
        # version the platform assigned rather than one this script assumed.
        trader = session.scalars(
            select(Trader).where(Trader.display_name == business.display_name)
        ).one()

        # A suspension is a decision about an *approved* business, which is the whole point
        # of the two axes: approval is the centre's verdict on the application, and
        # operational status is whether it may trade today. Seeding a suspended business
        # that was never approved would show a state the platform cannot reach.
        steps: list[str] = ["approve", "suspend"] if business.decision == "suspend" else [
            business.decision
        ]

        for step in steps:
            session.refresh(trader)
            trader_lifecycle.decide(
                trader_lifecycle.TraderDecision(
                    trader_id=trader.id,
                    expected_record_version=trader.record_version,
                    reason=business.reason if step != "approve" else None,
                ),
                names[step],
                session=session,
                policy=SEED_REDACTION,
                actor=AuditActor(actor_type="admin_user", actor_id=decider.id),
                context=context,
                now=now,
            )
            session.flush()

    for colleague in COLLEAGUES:
        password = _password()
        create_admin_user(
            NewAdminUser(
                username=colleague.username,
                full_name=colleague.full_name,
                password=password,
                role_codes=(colleague.role,),
            ),
            uow=uow,
            actor=AuditActor(actor_type="admin_user", actor_id=decider.id),
            context=context,
            idempotency_key=f"seed-{colleague.username}",
            policy=SEED_REDACTION,
            parameters=parameters,
            password_max_length=settings.password_max_length,
            now=now,
        )
        session.flush()
        credentials.append(("staff", colleague.username, password))

    return credentials


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.seed_demo",
        description=(
            "Populate a demonstration deployment with businesses in every state and staff "
            "in three roles. Refuses in production and refuses to run twice."
        ),
    )
    parser.parse_args(argv)

    settings = Settings()
    runtime = RuntimeServices.from_settings(settings)
    try:
        parameters = Argon2Parameters.from_settings(settings)
        with runtime.uow_factory() as uow:
            credentials = seed(uow, settings=settings, parameters=parameters, now=utc_now())
            uow.commit()
    except SeedRefused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return refusal.code
    finally:
        runtime.close()

    pending = sum(1 for business in BUSINESSES if business.decision is None)
    print(f"seeded {len(BUSINESSES)} businesses ({pending} awaiting a decision)")
    print(f"seeded {len(COLLEAGUES)} staff accounts")
    print("\ncredentials, shown once and stored nowhere:")
    for kind, identifier, password in credentials:
        print(f"  {kind:7} {identifier:14} {password}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
