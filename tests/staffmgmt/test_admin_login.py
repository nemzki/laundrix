from datetime import timedelta

from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models import AccountStatus, AuthEvent, Role, User
from app.models.staff_credential import utcnow
from config import TestingConfig
from tests.laundry.conftest import _make_app
from tests.staffmgmt.conftest import GOOD_PASSWORD


def make_admin(make_user, username="admin", **extra):
    return make_user(f"{username}@laundrix.invalid", role=Role.ADMIN, username=username,
                     password_hash=generate_password_hash(GOOD_PASSWORD), **extra)


def login(client, username="admin", password=GOOD_PASSWORD):
    return client.post("/auth/admin", data={"username": username, "password": password})


def signed_in(client):
    with client.session_transaction() as sess:
        return "_user_id" in sess


def test_legacy_admin_page_still_works_but_is_no_longer_linked(app):
    c = app.test_client()
    assert c.get("/auth/admin").status_code == 200
    page = c.get("/auth/login").data
    assert b"/auth/admin" not in page and b"/staff/login" not in page


def test_administrator_can_sign_in_with_username_and_password(app, make_user):
    admin = make_admin(make_user)
    c = app.test_client()
    r = login(c)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/admin")
    assert signed_in(c) and c.get("/dashboard/admin").status_code == 200
    db.session.expire_all()
    assert db.session.get(User, admin.id).last_login_at is not None
    assert db.session.execute(db.select(AuthEvent).filter_by(event="admin_login")).scalar_one()


def test_username_is_case_insensitive_but_password_is_exact(app, make_user):
    make_admin(make_user)
    assert login(app.test_client(), "ADMIN").status_code == 302
    assert login(app.test_client(), "admin", GOOD_PASSWORD.lower()).status_code == 401


def test_wrong_password_and_unknown_user_look_identical(app, make_user):
    make_admin(make_user)
    c = app.test_client()
    a, b = login(c, "admin", "wrong-password-1A!"), login(c, "nobody", "wrong-password-1A!")
    assert a.status_code == b.status_code == 401 and not signed_in(c)
    assert b"Invalid username or password." in a.data and b"Invalid username or password." in b.data
    assert GOOD_PASSWORD.encode() not in a.data


def test_lockout_after_repeated_failures_even_for_the_right_password(app, make_user):
    admin = make_admin(make_user)
    c = app.test_client()
    for _ in range(app.config["STAFF_MAX_FAILED_ATTEMPTS"]):
        assert login(c, password="wrong-password-1A!").status_code in (401, 423)
    assert login(c).status_code == 423 and not signed_in(c)
    admin.locked_until = utcnow() - timedelta(minutes=1)            # lock expires
    db.session.commit()
    assert login(c).status_code == 302 and signed_in(c)


def test_only_active_administrators_can_use_it(app, make_user):
    for i, kw in enumerate([{"account_status": AccountStatus.SUSPENDED, "active": False},
                            {"account_status": AccountStatus.DEACTIVATED, "active": False},
                            {"account_status": AccountStatus.PENDING_APPROVAL}]):
        make_admin(make_user, f"adm{i}", status=kw["account_status"], active=kw.get("active", True))
        c = app.test_client()
        assert login(c, f"adm{i}").status_code == 401 and not signed_in(c)


def test_staff_and_passwordless_accounts_cannot_use_it(app, make_user):
    make_user("s@example.com", role=Role.STAFF, username="staffer", password_hash=generate_password_hash(GOOD_PASSWORD))
    make_user("g@example.com", role=Role.ADMIN, username="googleadmin")          # Google-only admin: no password
    c = app.test_client()
    assert login(c, "staffer").status_code == 401
    assert login(c, "googleadmin", "").status_code == 401
    assert login(c, "googleadmin", "anything-1A!aaaa").status_code == 401


def test_it_can_be_switched_off(app, make_user):
    make_admin(make_user)
    app.config["ADMIN_PASSWORD_LOGIN_ENABLED"] = False
    c = app.test_client()
    assert c.get("/auth/admin").status_code == 404 and login(c).status_code == 404
    assert b"/auth/admin" not in c.get("/auth/login").data


def test_a_new_session_is_started_on_login(app, make_user):
    make_admin(make_user)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["attacker_planted"] = "yes"
    login(c)
    with c.session_transaction() as sess:
        assert "attacker_planted" not in sess


def test_csrf_is_enforced_on_the_login_form():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        assert app.test_client().post("/auth/admin", data={"username": "admin", "password": "x"}).status_code == 400
        db.session.remove()
        db.drop_all()
