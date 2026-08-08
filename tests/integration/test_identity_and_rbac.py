"""The identity and RBAC constraints, each proven by a row the database refuses.

No authentication behaviour is tested here because none exists yet — that is M3.
What is tested is the shape M3 will depend on, and the specific shapes are
decisions rather than defaults: two tables instead of one, a surrogate key on
grants instead of a composite, partial uniqueness with two conditions instead of
one.

Covers: DB-IDENTITY-001, SEC-RBAC-001, SEC-RBAC-002, DB-TRADER-001, DB-OWN-001,
DB-PRIMARY-001, DB-PRIMARY-002, DB-PRIMARY-003, DB-ACCT-001.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.time import utc_now  # noqa: E402
from app.db.models.identity import ACCOUNT_STATUSES, AdminUser, TraderUser  # noqa: E402
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission  # noqa: E402
from app.db.models.trader import Trader  # noqa: E402

pytestmark = pytest.mark.integration


def _sqlalchemy_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


@pytest.fixture
def session_factory(migrated_database: str) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(_sqlalchemy_url(migrated_database))
    try:
        yield sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(session_factory: sessionmaker[Session]) -> Iterator[None]:
    yield
    with session_factory() as session:
        for table in (
            "admin_user_roles",
            "role_permissions",
            "roles",
            "permissions",
            "trader_users",
            "traders",
            "admin_users",
        ):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


def admin(username: str = "operator", **overrides: object) -> AdminUser:
    values: dict[str, object] = {
        "username": username,
        "full_name": "Operator",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "status": "active",
        **overrides,
    }
    return AdminUser(**values)  # type: ignore[arg-type]


def business(phone: str = "+982100000000", **overrides: object) -> Trader:
    """A trader business. Ownership scopes to one of these, never to a login."""

    values: dict[str, object] = {
        "display_name": "Gold Trading Co",
        "primary_phone": phone,
        "operational_status": "active",
        "approval_status": "approved",
        **overrides,
    }
    return Trader(**values)  # type: ignore[arg-type]


def trader(
    phone: str = "+989120000000", *, trader_id: uuid.UUID | None = None, **overrides: object
) -> TraderUser:
    values: dict[str, object] = {
        "phone_number": phone,
        "full_name": "Trader",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "status": "active",
        "trader_id": trader_id,
        **overrides,
    }
    return TraderUser(**values)  # type: ignore[arg-type]


@pytest.fixture
def one_business(session_factory: sessionmaker[Session]) -> uuid.UUID:
    """A committed trader business, for the tests that need only one."""

    with session_factory() as session:
        row = business()
        session.add(row)
        session.commit()
        return row.id


class TestIdentitySeparation:
    def test_the_two_domains_are_separate_tables(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The property M3's cross-surface rejection test depends on.

        With one table and a type flag, "an admin session is rejected on a trader
        surface" cannot be falsified — the same row satisfies both queries.
        """

        with session_factory() as session:
            tables = {
                row[0]
                for row in session.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            }

        assert {"admin_users", "trader_users"} <= tables

    def test_an_admin_and_a_trader_may_share_a_phone_number(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID
    ) -> None:
        """They are different people in different domains.

        A shared table would have forced a single uniqueness rule across both.
        """

        with session_factory() as session:
            session.add(admin(phone_number="+989120000000"))
            session.add(trader(phone="+989120000000", trader_id=one_business))
            session.commit()


class TestAdminUniqueness:
    def test_usernames_are_case_insensitively_unique(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """CITEXT, so no lookup can forget to lower() and let a duplicate in."""

        with session_factory() as session:
            session.add(admin("Operator"))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin("operator"))
            session.commit()

    def test_many_admins_may_have_no_email(self, session_factory: sessionmaker[Session]) -> None:
        """Partial uniqueness: absent is not a value that collides."""

        with session_factory() as session:
            session.add_all([admin("one"), admin("two"), admin("three")])
            session.commit()

    def test_two_admins_cannot_share_an_email(self, session_factory: sessionmaker[Session]) -> None:
        with session_factory() as session:
            session.add(admin("one", email="a@example.com"))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin("two", email="A@Example.com"))
            session.commit()


class TestTraderPrimaryContact:
    """One primary contact **per business**, which is not what M2 enforced.

    `04_Database_Schema.md:360-362` keys the index on `trader_users(trader_id)`.
    `20260801_0007` keyed it on `is_primary`, because `trader_id` did not exist and
    the flag was the only column left — so the constraint that shipped was "one
    primary contact in the entire database".

    The test that used to stand here asserted exactly that: it added two primary
    contacts with different phone numbers and required the **second to be
    rejected**. Written from the built index rather than from the specification, it
    passed, and it made the defect look deliberate. That is the failure mode worth
    naming — a test can pin a bug as though it were a decision, and then the bug has
    a defender.

    Covers: DB-PRIMARY-001, DB-PRIMARY-002, DB-PRIMARY-003.
    """

    def test_two_businesses_may_each_have_their_own_primary_contact(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The regression test. This is what registering a second trader does.

        Under the index M2 shipped, the second business's primary contact is
        rejected by `uq_trader_users_primary_contact` — a unique violation on a
        column the caller never set.
        """

        with session_factory() as session:
            first, second = business("+982100000001"), business("+982100000002")
            session.add_all([first, second])
            session.commit()
            first_id, second_id = first.id, second.id

        with session_factory() as session:
            session.add(trader("+989120000001", trader_id=first_id, is_primary=True))
            session.add(trader("+989120000002", trader_id=second_id, is_primary=True))
            session.commit()

            count = session.execute(
                text("SELECT count(*) FROM trader_users WHERE is_primary")
            ).scalar_one()

        assert count == 2

    def test_one_business_may_not_have_two_primary_contacts(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID
    ) -> None:
        """The constraint that is actually wanted, scoped to a business."""

        with session_factory() as session:
            session.add(trader("+989120000001", trader_id=one_business, is_primary=True))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError) as raised:
            session.add(trader("+989120000002", trader_id=one_business, is_primary=True))
            session.commit()

        assert "uq_trader_users_one_primary" in str(raised.value), (
            "the row was rejected, but not by the per-business index — something "
            f"else refused it first, so that constraint is still unproven:\n{raised.value}"
        )

    def test_a_deactivated_former_primary_does_not_block_a_replacement(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID
    ) -> None:
        """The second condition on the partial index, and the reason it is there.

        With `WHERE is_primary = TRUE` alone, retiring a primary contact would
        permanently prevent appointing a replacement — the old row still matches.

        The predicate names `deactivated`, not `inactive`. That is not cosmetic:
        `inactive` is a `traders.operational_status` value and DOC-CONFLICT-037
        refuses it as an account state, so `ck_trader_users_status` now rejects it.
        Had the predicate kept the old spelling it would name a value the CHECK
        forbids, no row could ever match `status <> 'inactive'` falsely, and the
        partial index would quietly degenerate into `WHERE is_primary = TRUE`.
        """

        with session_factory() as session:
            session.add(
                trader(
                    "+989120000001",
                    trader_id=one_business,
                    is_primary=True,
                    status="deactivated",
                )
            )
            session.commit()

        with session_factory() as session:
            session.add(
                trader("+989120000002", trader_id=one_business, is_primary=True, status="active")
            )
            session.commit()

    def test_the_index_predicate_names_a_status_the_check_admits(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Guard the guard: the test above is vacuous if the two disagree.

        A predicate referencing a value no row may hold is not a narrower index —
        it is an index whose second condition can never be false, which is the same
        as not having it. Read from the catalogue side rather than asserting the
        literal, so renaming the value in one place fails here.
        """

        with session_factory() as session:
            predicate = session.execute(
                text(
                    "SELECT pg_get_expr(indpred, indrelid) FROM pg_index "
                    "WHERE indexrelid = 'uq_trader_users_one_primary'::regclass"
                )
            ).scalar_one()

        excluded = {value for value in ACCOUNT_STATUSES if f"'{value}'" in predicate}

        assert excluded, (
            "the primary-contact predicate references no account status at all, so "
            f"its second condition constrains nothing: {predicate}"
        )
        assert excluded == {"deactivated"}, (
            f"the predicate excludes {sorted(excluded)}; only 'deactivated' is the "
            "retired-account state, and any other value here means the index and "
            "ck_trader_users_status disagree about what an account status is"
        )

    def test_many_contacts_of_one_business_may_be_non_primary(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID
    ) -> None:
        with session_factory() as session:
            session.add_all(
                [
                    trader(f"+98912000{index:04d}", trader_id=one_business, is_primary=False)
                    for index in range(3)
                ]
            )
            session.commit()


class TestTraderBusiness:
    """The ownership root, and the two columns that are deliberately absent.

    Covers: DB-TRADER-001, DB-OWN-001.
    """

    def test_the_columns_match_document_04(self, session_factory: sessionmaker[Session]) -> None:
        with session_factory() as session:
            columns = {
                row[0]
                for row in session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'traders'"
                    )
                )
            }

        assert columns == {
            "id",
            "display_name",
            "legal_name",
            "primary_phone",
            "operational_status",
            "approval_status",
            "approved_at",
            "approved_by_admin_user_id",
            "risk_level",
            "credit_limit_irr",
            "notes_internal",
            "record_version",
            "created_at",
            "updated_at",
        }

    def test_there_is_no_stored_balance(self, session_factory: sessionmaker[Session]) -> None:
        """`04_Database_Schema.md:469` prohibits it without a ledger.

        A cached balance with no ledger behind it is a number that looks
        authoritative and reconciles against nothing.
        """

        with session_factory() as session:
            balance_like = [
                row[0]
                for row in session.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'traders' "
                        "AND column_name LIKE '%balance%'"
                    )
                )
            ]

        assert balance_like == []

    def test_there_is_no_combined_status_column(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """DOC-CONFLICT-024's structural half, enforced by absence.

        Document 05 exposes one `status`; documents 04 and 12 carry three separate
        facts. The projection is computed at read time, and the way to guarantee it
        never drifts from its three sources is for there to be nothing to drift.
        """

        with session_factory() as session:
            exists = session.execute(
                text(
                    "SELECT count(*) FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'traders' "
                    "AND column_name = 'status'"
                )
            ).scalar_one()

        assert exists == 0

    def test_a_negative_credit_limit_is_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(business(credit_limit_irr=-1))
            session.commit()

    def test_no_credit_limit_is_not_a_zero_credit_limit(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The CHECK admits NULL on purpose: unrecorded is not the same as none."""

        with session_factory() as session:
            session.add(business(credit_limit_irr=None))
            session.commit()

    def test_a_trader_login_must_name_an_existing_business(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """`trader_id` is the only source of `ActorContext.trader_id`.

        A login whose business does not exist would be an actor with an ownership
        scope nothing can resolve — so the foreign key refuses it rather than
        leaving M3's guards to discover it at request time.
        """

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(trader(trader_id=uuid.uuid4()))
            session.commit()

    def test_a_trader_login_cannot_exist_without_a_business(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(trader(trader_id=None))
            session.commit()


class TestAccountStatusValues:
    """The four values DOC-CONFLICT-037 decided, and the three it refused.

    Covers: DB-ACCT-001.
    """

    @pytest.mark.parametrize(
        ("index", "status"), list(enumerate(ACCOUNT_STATUSES)), ids=ACCOUNT_STATUSES
    )
    def test_each_decided_status_is_accepted(
        self,
        session_factory: sessionmaker[Session],
        one_business: uuid.UUID,
        index: int,
        status: str,
    ) -> None:
        """Anchor the rejections below: without this they could all be vacuous.

        The phone number is derived from the parameter index rather than from
        `hash(status)`, which varies between processes and would make a collision
        appear on some runs and not others.
        """

        with session_factory() as session:
            session.add(admin(f"admin_{status}", status=status))
            session.add(trader(f"+98912000{index:04d}", trader_id=one_business, status=status))
            session.commit()

    @pytest.mark.parametrize("status", ["locked", "pending", "inactive", "pending_approval", ""])
    def test_a_refused_status_is_rejected_on_both_tables(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID, status: str
    ) -> None:
        """Each refusal is a decision recorded in DOC-CONFLICT-037, not an omission.

        `locked` is `locked_until`; `pending` belongs to the business's approval
        axis; `inactive` is a `traders.operational_status` value. The empty string
        is here because a CHECK that lists values still admits one nobody listed if
        the column is merely `VARCHAR`.
        """

        with session_factory() as session, pytest.raises(IntegrityError) as raised:
            session.add(admin("someone", status=status))
            session.commit()
        assert "ck_admin_users_status" in str(raised.value)

        with session_factory() as session, pytest.raises(IntegrityError) as raised:
            session.add(trader(trader_id=one_business, status=status))
            session.commit()
        assert "ck_trader_users_status" in str(raised.value)


class TestSecurityStamp:
    def test_both_identity_tables_carry_a_stamp(
        self, session_factory: sessionmaker[Session], one_business: uuid.UUID
    ) -> None:
        """Doc 04 omits it; doc 12 requires it.

        Without a stamp on the identity *and* on the session, a password change
        or role revocation leaves authority live in an existing session: it is
        still signed, still unexpired, and still carries what was taken away.
        """

        with session_factory() as session:
            session.add(admin())
            session.add(trader(trader_id=one_business))
            session.commit()

            admin_stamp = session.execute(
                text("SELECT security_stamp_version FROM admin_users")
            ).scalar()
            trader_stamp = session.execute(
                text("SELECT security_stamp_version FROM trader_users")
            ).scalar()

        assert admin_stamp == 1
        assert trader_stamp == 1

    def test_a_zero_stamp_is_refused(self, session_factory: sessionmaker[Session]) -> None:
        """Zero would compare equal to an unset session value."""

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin(security_stamp_version=0))
            session.commit()


class TestRoleGrants:
    def _role_and_admin(
        self, session_factory: sessionmaker[Session]
    ) -> tuple[uuid.UUID, uuid.UUID]:
        with session_factory() as session:
            role = Role(code="manager", description="Approves batch versions")
            person = admin()
            session.add_all([role, person])
            session.commit()
            return person.id, role.id

    def test_a_role_can_be_revoked_and_granted_again(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The reason the table has a surrogate key.

        A composite (admin_user_id, role_id) primary key forces a choice between
        destroying the revocation record and refusing the second grant. Somebody
        changing team and coming back is ordinary.
        """

        admin_id, role_id = self._role_and_admin(session_factory)

        with session_factory() as session:
            session.add(AdminUserRole(admin_user_id=admin_id, role_id=role_id))
            session.commit()

        with session_factory() as session:
            session.execute(
                text("UPDATE admin_user_roles SET revoked_at = now() WHERE revoked_at IS NULL")
            )
            session.commit()

        with session_factory() as session:
            session.add(AdminUserRole(admin_user_id=admin_id, role_id=role_id))
            session.commit()

        with session_factory() as session:
            total, live = session.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE revoked_at IS NULL) "
                    "FROM admin_user_roles"
                )
            ).one()

        assert total == 2, "the revoked grant was destroyed rather than retained"
        assert live == 1

    def test_two_live_grants_of_one_role_are_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        admin_id, role_id = self._role_and_admin(session_factory)

        with session_factory() as session:
            session.add(AdminUserRole(admin_user_id=admin_id, role_id=role_id))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(AdminUserRole(admin_user_id=admin_id, role_id=role_id))
            session.commit()

    def test_deleting_an_admin_does_not_erase_their_grant_history(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """No cascade here, deliberately.

        Who held what authority and when is exactly what an audit asks, and a
        cascade would answer "nobody" once the account is gone.
        """

        admin_id, role_id = self._role_and_admin(session_factory)

        with session_factory() as session:
            session.add(AdminUserRole(admin_user_id=admin_id, role_id=role_id))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.execute(text("DELETE FROM admin_users WHERE id = :id"), {"id": admin_id})
            session.commit()


class TestRolePermissions:
    def test_deleting_a_role_removes_its_permission_pairs(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The one sanctioned cascade, and why it is safe here.

        The row carries no history: a pair is either in the set or not. Leaving
        orphans pointing at a deleted role would be worse than removing them.
        """

        with session_factory() as session:
            role = Role(code="auditor")
            permission = Permission(code="audit.read", domain="identity_access")
            session.add_all([role, permission])
            session.commit()
            session.add(RolePermission(role_id=role.id, permission_id=permission.id))
            session.commit()
            role_id = role.id

        with session_factory() as session:
            session.execute(text("DELETE FROM roles WHERE id = :id"), {"id": role_id})
            session.commit()
            remaining = session.execute(text("SELECT count(*) FROM role_permissions")).scalar()

        assert remaining == 0

    def test_a_permission_code_must_be_dotted_and_lowercase(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Doc 12's identifiers are dotted lowercase; doc 05's API spellings are
        deprecated aliases and deliberately not rows here."""

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(Permission(code="Audit.Read", domain="identity_access"))
            session.commit()

    def test_a_permission_without_a_dot_is_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(Permission(code="auditread", domain="identity_access"))
            session.commit()


class TestFailedLoginCountersAreDurable:
    def test_the_counter_and_lock_live_in_postgresql(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """`infra/redis/redis.conf` sets appendonly no and save "" — zero
        persistence. A Redis-only lockout resets on restart, and an attacker only
        has to wait for one."""

        with session_factory() as session:
            person = admin()
            session.add(person)
            session.commit()
            session.execute(
                text(
                    "UPDATE admin_users SET failed_login_count = 5, "
                    "locked_until = :until WHERE id = :id"
                ),
                {"until": utc_now(), "id": person.id},
            )
            session.commit()

        with session_factory() as session:
            count, locked = session.execute(
                text("SELECT failed_login_count, locked_until FROM admin_users")
            ).one()

        assert count == 5
        assert locked is not None

    def test_a_negative_counter_is_refused(self, session_factory: sessionmaker[Session]) -> None:
        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin(failed_login_count=-1))
            session.commit()
