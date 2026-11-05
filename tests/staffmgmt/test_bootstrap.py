import logging

from click.testing import CliRunner
from werkzeug.security import check_password_hash

from app.auth import bootstrap
from app.extensions import db
from app.models import AccountStatus, AuthEvent, Role, User
from tests.staffmgmt.conftest import GOOD_PASSWORD


def admins():
    return db.session.scalars(db.select(User).filter_by(role=Role.ADMIN)).all()


def run(app, *args):
    return app.test_cli_runner().invoke(args=["bootstrap-admin", *args])


def configure(app, username="admin", password=GOOD_PASSWORD, email=None):
    app.config.update(INITIAL_ADMIN_USERNAME=username, INITIAL_ADMIN_PASSWORD=password, INITIAL_ADMIN_EMAIL=email)


def test_initial_admin_is_created_active_and_hashed(app):
    configure(app)
    r = run(app)
    assert r.exit_code == 0 and "created" in r.output
    (admin,) = admins()
    assert admin.username == "admin" and admin.email == "admin@laundrix.invalid"
    assert admin.is_active and admin.account_status == AccountStatus.ACTIVE and admin.approved_at is not None
    assert admin.password_hash != GOOD_PASSWORD and GOOD_PASSWORD not in admin.password_hash
    assert check_password_hash(admin.password_hash, GOOD_PASSWORD)
    assert GOOD_PASSWORD not in r.output                            # never printed
    event = db.session.execute(db.select(AuthEvent).filter_by(event="admin_bootstrap")).scalar_one()
    assert event.target_user_id == admin.id and GOOD_PASSWORD not in (event.detail or "")


def test_running_it_again_never_duplicates_or_overwrites(app):
    configure(app)
    run(app)
    original = admins()[0].password_hash
    configure(app, password="Different-Pass-Word-77")              # even a different env password
    r = run(app)
    assert r.exit_code == 0 and "already exists" in r.output
    assert len(admins()) == 1
    db.session.expire_all()
    assert admins()[0].password_hash == original
    assert db.session.scalar(db.select(db.func.count(AuthEvent.id)).filter_by(event="admin_bootstrap")) == 1


def test_existing_google_admin_is_preserved_and_no_second_admin_is_forced(app, make_user):
    google_admin = make_user("owner@example.com", role=Role.ADMIN)
    configure(app)
    r = run(app)
    assert r.exit_code == 0 and "already exists" in r.output and len(admins()) == 1
    assert db.session.get(User, google_admin.id).username is None
    forced = run(app, "--allow-additional")
    assert forced.exit_code == 0 and len(admins()) == 2


def test_missing_or_weak_passwords_fail_safely(app):
    for bad in (None, "", "short1A!", "alllowercaseletters", "ONLYUPPERCASELETTERS1", "admin-Admin-123", "password1234"):
        configure(app, password=bad)
        r = run(app)
        assert r.exit_code == 1, bad
        assert "INITIAL_ADMIN_PASSWORD" in r.output
        if bad:
            assert bad not in r.output
    assert admins() == []


def test_invalid_username_is_rejected(app):
    configure(app, username="Bad Name!")
    assert run(app).exit_code == 1 and admins() == []


def test_username_of_a_non_admin_account_is_never_taken_over(app, make_user):
    make_user("s@example.com", username="admin")
    configure(app)
    r = run(app)
    assert r.exit_code == 1 and "non-administrator" in r.output
    assert db.session.execute(db.select(User).filter_by(username="admin")).scalar_one().role == Role.STAFF


def test_password_rules():
    ok = bootstrap.password_problems
    assert ok(GOOD_PASSWORD, "admin") == []
    assert ok("a" * 300 + "A1!") != []
    assert ok("Contains-admin-Inside-1", "admin") != []


def test_the_password_never_reaches_the_logs(app, caplog):
    configure(app)
    with caplog.at_level(logging.DEBUG):
        run(app)
    assert GOOD_PASSWORD not in caplog.text


def test_rotating_the_password(app):
    configure(app)
    run(app)
    admin = admins()[0]
    admin.failed_login_attempts = 4
    db.session.commit()
    new = "Brand-New-Passw0rd-42"
    r = app.test_cli_runner().invoke(args=["rotate-admin-password"], input=f"{new}\n{new}\n")
    assert r.exit_code == 0 and new not in r.output
    db.session.expire_all()
    admin = admins()[0]
    assert check_password_hash(admin.password_hash, new) and not check_password_hash(admin.password_hash, GOOD_PASSWORD)
    assert admin.failed_login_attempts == 0
    assert db.session.execute(db.select(AuthEvent).filter_by(event="admin_password_rotated")).scalar_one()
    weak = app.test_cli_runner().invoke(args=["rotate-admin-password"], input="weak\nweak\n")
    assert weak.exit_code == 1
    unknown = app.test_cli_runner().invoke(args=["rotate-admin-password", "nobody"], input=f"{new}\n{new}\n")
    assert unknown.exit_code == 1
