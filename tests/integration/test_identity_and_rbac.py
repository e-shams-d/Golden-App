"""The identity and RBAC constraints, each proven by a row the database refuses.

No authentication behaviour is tested here because none exists yet — that is M3.
What is tested is the shape M3 will depend on, and the specific shapes are
decisions rather than defaults: two tables instead of one, a surrogate key on
grants instead of a composite, partial uniqueness with two conditions instead of
one.

Covers: DB-IDENTITY-001, SEC-RBAC-001, SEC-RBAC-002.
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
from app.db.models.identity import AdminUser, TraderUser  # noqa: E402
from app.db.models.rbac import AdminUserRole, Permission, Role, RolePermission  # noqa: E402

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


def trader(phone: str = "+989120000000", **overrides: object) -> TraderUser:
    values: dict[str, object] = {
        "phone_number": phone,
        "full_name": "Trader",
        "password_hash": "$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        "status": "active",
        **overrides,
    }
    return TraderUser(**values)  # type: ignore[arg-type]


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
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """They are different people in different domains.

        A shared table would have forced a single uniqueness rule across both.
        """

        with session_factory() as session:
            session.add(admin(phone_number="+989120000000"))
            session.add(trader(phone="+989120000000"))
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

    def test_many_admins_may_have_no_email(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Partial uniqueness: absent is not a value that collides."""

        with session_factory() as session:
            session.add_all([admin("one"), admin("two"), admin("three")])
            session.commit()

    def test_two_admins_cannot_share_an_email(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(admin("one", email="a@example.com"))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin("two", email="A@Example.com"))
            session.commit()


class TestTraderPrimaryContact:
    def test_only_one_active_primary_contact(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add(trader("+989120000001", is_primary=True))
            session.commit()

        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(trader("+989120000002", is_primary=True))
            session.commit()

    def test_an_inactive_former_primary_does_not_block_a_new_one(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """The second condition on the partial index, and the reason it is there.

        With `WHERE is_primary = TRUE` alone, deactivating a primary contact
        would permanently prevent appointing a replacement — the old row still
        matches.
        """

        with session_factory() as session:
            session.add(trader("+989120000001", is_primary=True, status="inactive"))
            session.commit()

        with session_factory() as session:
            session.add(trader("+989120000002", is_primary=True, status="active"))
            session.commit()

    def test_many_traders_may_be_non_primary(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session:
            session.add_all(
                [trader(f"+98912000{index:04d}", is_primary=False) for index in range(3)]
            )
            session.commit()


class TestSecurityStamp:
    def test_both_identity_tables_carry_a_stamp(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        """Doc 04 omits it; doc 12 requires it.

        Without a stamp on the identity *and* on the session, a password change
        or role revocation leaves authority live in an existing session: it is
        still signed, still unexpired, and still carries what was taken away.
        """

        with session_factory() as session:
            session.add(admin())
            session.add(trader())
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
            remaining = session.execute(
                text("SELECT count(*) FROM role_permissions")
            ).scalar()

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

    def test_a_negative_counter_is_refused(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        with session_factory() as session, pytest.raises(IntegrityError):
            session.add(admin(failed_login_count=-1))
            session.commit()
