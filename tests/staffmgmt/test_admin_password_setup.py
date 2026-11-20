"""A Google-created administrator (no username, no password) can be given a password."""
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models import Role, User

NEW = "Brand-New-Passw0rd-42"


def _rotate(app, ident, password=NEW):
    return app.test_cli_runner().invoke(args=["rotate-admin-password", ident], input=f"{password}\n{password}\n")


def test_google_admin_gets_a_password_by_email(app, make_user):
    admin = make_user("owner@example.com", role=Role.ADMIN)
    assert admin.password_hash is None
    result = _rotate(app, "owner@example.com")
    assert result.exit_code == 0 and NEW not in result.output
    db.session.expire_all()
    assert check_password_hash(db.session.get(User, admin.id).password_hash, NEW)


def test_password_sign_in_then_works_with_the_email(app, make_user):
    make_user("owner@example.com", role=Role.ADMIN)
    _rotate(app, "owner@example.com")
    from app.auth.credentials import authenticate
    with app.test_request_context():
        assert authenticate("owner@example.com", NEW).ok
        assert not authenticate("owner@example.com", "wrong-password-123").ok


def test_staff_and_unknown_accounts_are_refused(app, make_user):
    make_user("worker@example.com", role=Role.STAFF)
    assert _rotate(app, "worker@example.com").exit_code == 1
    assert _rotate(app, "nobody@example.com").exit_code == 1


def test_password_cannot_contain_the_email_name(app, make_user):
    make_user("owner@example.com", role=Role.ADMIN)
    assert _rotate(app, "owner@example.com", "Owner-Passw0rd-1234").exit_code == 1


def test_initial_admin_settings_exist_on_the_config(app):
    for key in ("INITIAL_ADMIN_USERNAME", "INITIAL_ADMIN_PASSWORD", "INITIAL_ADMIN_EMAIL"):
        assert key in app.config
