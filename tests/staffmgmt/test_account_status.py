import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AccountStatus, Role, User


def test_users_created_the_old_way_are_active(app):
    """Existing code and tests create users without any status: they must stay fully active."""
    u = User(email="legacy@example.com", role=Role.STAFF, is_active=True)
    db.session.add(u)
    db.session.commit()
    assert u.account_status == AccountStatus.ACTIVE and u.is_operational
    assert u.username is None and u.password_hash is None and u.failed_login_attempts == 0 and not u.is_locked


@pytest.mark.parametrize("status,operational", [
    (AccountStatus.ACTIVE, True), (AccountStatus.PENDING_VERIFICATION, False),
    (AccountStatus.PENDING_APPROVAL, False), (AccountStatus.REJECTED, False),
    (AccountStatus.SUSPENDED, False), (AccountStatus.DEACTIVATED, False),
])
def test_only_active_accounts_are_operational(make_user, status, operational):
    assert make_user(f"{status}@example.com", status=status).is_operational is operational


def test_disabled_flag_overrides_an_active_status(make_user):
    assert make_user("off@example.com", active=False).is_operational is False


def test_database_rejects_unknown_statuses(app):
    db.session.add(User(email="bad@example.com", role=Role.STAFF, account_status="superuser"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_usernames_are_unique(make_user):
    make_user("a@example.com", role=Role.ADMIN, username="boss")
    with pytest.raises(IntegrityError):
        make_user("b@example.com", role=Role.ADMIN, username="boss")
    db.session.rollback()


def test_status_groups_are_consistent():
    assert set(AccountStatus.PENDING) | set(AccountStatus.BLOCKED) | {AccountStatus.ACTIVE} == set(AccountStatus.ALL)
    assert set(AccountStatus.LABELS) == set(AccountStatus.TONES) == set(AccountStatus.ALL)
