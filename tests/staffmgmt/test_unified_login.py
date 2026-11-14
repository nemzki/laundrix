"""The single login page: Google, or username/email + password for administrators and staff."""
import uuid
from datetime import timedelta

import pytest
from werkzeug.security import generate_password_hash

from app.auth import services as google_auth
from app.extensions import db
from app.models import AccountStatus, AuthEvent, IdentityVerification, Role, User
from app.models.staff_credential import utcnow
from app.staff_auth.services import create_staff
from config import TestingConfig
from tests.laundry.conftest import _make_app
from tests.staffmgmt.conftest import GOOD_PASSWORD, STAFF_PASSWORD

S = AccountStatus


def make_admin(make_user, username="admin", email="admin@laundrix.invalid", **extra):
    return make_user(email, role=Role.ADMIN, username=username, password_hash=generate_password_hash(GOOD_PASSWORD), **extra)


def make_staff(email="sam@example.com", status=S.ACTIVE, verified=True, active=True, password=STAFF_PASSWORD):
    user, _tok = create_staff(email, "Sam Cruz", account_status=status)
    user.staff_credential.password_hash = generate_password_hash(password)
    user.is_active = active
    if verified:
        db.session.add(IdentityVerification(
            user_id=user.id, provider="didit", provider_session_id=str(uuid.uuid4()), environment="sandbox",
            status="verified", purpose="kyc", decided_at=utcnow(), completed_at=utcnow()))
    db.session.commit()
    return user


def sign_in(client, identifier, password):
    return client.post("/auth/login", data={"identifier": identifier, "password": password})


def signed_in(client):
    with client.session_transaction() as sess:
        return "_user_id" in sess


# ----------------------------------------------------------------------------- the page
def test_one_clean_login_page(app):
    c = app.test_client()
    page = c.get("/auth/login").get_data(as_text=True)
    for text in ("Sign In", "Welcome to Laundrix. Sign in to continue.", "Continue with Google", "or",
                 "Email or Username", "Password", "authorized by your administrator",
                 'name="identifier"', 'name="password"', 'name="csrf_token"', "Admin", "Staff"):
        assert text in page, text
    for gone in ("/staff/login", "/auth/admin", "Staff Portal", "Administrator sign-in", "Back to Home"):
        assert gone not in page, gone
    assert "lx-logo--mark-only" in page
    assert 'class="lx-logo__text"' not in page
    landing = c.get("/").get_data(as_text=True)
    assert "/staff/login" not in landing
    assert "laundrix-mascot.png" in landing
    assert "Does Laundrix automatically process GCash payments?" not in landing
    assert "Built for Wash Up! Laundry Shop" in landing
    assert 'href="/auth/login"' in landing


def test_signed_in_users_are_sent_to_their_own_dashboard(app, make_user, client_for):
    assert client_for(make_admin(make_user)).get("/auth/login").headers["Location"].endswith("/dashboard/admin")
    assert client_for(make_staff()).get("/auth/login").headers["Location"].endswith("/dashboard/staff")


# ----------------------------------------------------------------------------- administrators
@pytest.mark.parametrize("identifier", ["admin", "ADMIN", " admin ", "admin@laundrix.invalid", "Admin@Laundrix.invalid"])
def test_admin_signs_in_with_username_or_email(app, make_user, identifier):
    make_admin(make_user)
    c = app.test_client()
    r = sign_in(c, identifier, GOOD_PASSWORD)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/admin")
    assert signed_in(c) and c.get("/dashboard/admin").status_code == 200
    assert events("admin_login")


def events(name):
    db.session.expire_all()
    return db.session.scalars(db.select(AuthEvent).filter_by(event=name)).all()


def test_admin_password_login_can_be_switched_off(app, make_user):
    make_admin(make_user)
    app.config["ADMIN_PASSWORD_LOGIN_ENABLED"] = False
    c = app.test_client()
    assert sign_in(c, "admin", GOOD_PASSWORD).status_code == 401 and not signed_in(c)


# ----------------------------------------------------------------------------- staff
def test_staff_sign_in_with_email_and_reach_the_staff_dashboard(app):
    make_staff()
    c = app.test_client()
    r = sign_in(c, "SAM@example.com", STAFF_PASSWORD)
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/staff")
    assert signed_in(c) and c.get("/dashboard/staff").status_code == 200
    assert events("password_login_success")


def test_staff_use_their_email_username_is_only_honoured_if_one_was_assigned(app):
    """Staff Management never assigns usernames, so staff sign in with email. The shared lookup does
    accept a username for any account that has one."""
    user = make_staff()
    assert user.username is None
    assert sign_in(app.test_client(), "sam", STAFF_PASSWORD).status_code == 401
    user.username = "sam.cruz"
    db.session.commit()
    assert sign_in(app.test_client(), "sam.cruz", STAFF_PASSWORD).status_code == 302


def test_staff_credentials_never_unlock_an_admin_and_vice_versa(app, make_user):
    make_admin(make_user)
    make_staff()
    assert sign_in(app.test_client(), "admin", STAFF_PASSWORD).status_code == 401
    assert sign_in(app.test_client(), "sam@example.com", GOOD_PASSWORD).status_code == 401


# ----------------------------------------------------------------------------- failures
def test_invalid_credentials_get_one_generic_answer(app, make_user):
    make_admin(make_user)
    make_staff()
    c = app.test_client()
    answers = {sign_in(c, who, "Wrong-Password-1!").get_data(as_text=True).count("Invalid username or password.")
               for who in ("admin", "sam@example.com", "nobody", "nobody@example.com", "")}
    assert answers == {1}
    r = sign_in(c, "sam@example.com", "Wrong-Password-1!")
    assert r.status_code == 401 and not signed_in(c)
    assert b'value="sam@example.com"' in r.data and b"Wrong-Password-1!" not in r.data     # identifier kept, password never echoed


def test_staff_accounts_lock_after_repeated_failures(app):
    make_staff()
    c = app.test_client()
    for _ in range(app.config["STAFF_MAX_FAILED_ATTEMPTS"]):
        assert sign_in(c, "sam@example.com", "Wrong-Password-1!").status_code in (401, 423)
    r = sign_in(c, "sam@example.com", STAFF_PASSWORD)
    assert r.status_code == 423 and b"temporarily locked" in r.data and not signed_in(c)
    user = db.session.execute(db.select(User).filter_by(email="sam@example.com")).scalar_one()
    user.staff_credential.locked_until = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert sign_in(c, "sam@example.com", STAFF_PASSWORD).status_code == 302


def test_admin_accounts_lock_after_repeated_failures(app, make_user):
    admin = make_admin(make_user)
    c = app.test_client()
    for _ in range(app.config["STAFF_MAX_FAILED_ATTEMPTS"]):
        sign_in(c, "admin", "Wrong-Password-1!")
    assert sign_in(c, "admin", GOOD_PASSWORD).status_code == 423 and not signed_in(c)
    admin.locked_until = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert sign_in(c, "admin", GOOD_PASSWORD).status_code == 302


def test_a_successful_sign_in_resets_the_failure_counter(app, make_user):
    admin = make_admin(make_user)
    c = app.test_client()
    sign_in(c, "admin", "Wrong-Password-1!")
    assert db.session.get(User, admin.id).failed_login_attempts == 1
    sign_in(c, "admin", GOOD_PASSWORD)
    db.session.expire_all()
    assert db.session.get(User, admin.id).failed_login_attempts == 0


# ----------------------------------------------------------------------------- pending and blocked accounts
def test_pending_staff_are_told_why_only_after_proving_their_password(app):
    make_staff("w@example.com", status=S.PENDING_APPROVAL)
    make_staff("v@example.com", status=S.PENDING_VERIFICATION, verified=False)
    for email, text in (("w@example.com", b"awaiting administrator approval"), ("v@example.com", b"setup is incomplete")):
        c = app.test_client()
        r = sign_in(c, email, STAFF_PASSWORD)
        assert r.status_code == 403 and text in r.data and not signed_in(c)
        wrong = sign_in(app.test_client(), email, "Wrong-Password-1!")
        assert wrong.status_code == 401 and text not in wrong.data                 # no status leak without the password


@pytest.mark.parametrize("status", AccountStatus.BLOCKED)
def test_blocked_staff_cannot_sign_in(app, status):
    make_staff(status=status, active=False)
    c = app.test_client()
    r = sign_in(c, "sam@example.com", STAFF_PASSWORD)
    assert r.status_code == 401 and not signed_in(c) and b"Invalid username or password." in r.data


def test_disabled_staff_cannot_sign_in_even_if_the_status_still_says_active(app):
    make_staff(active=False)
    assert sign_in(app.test_client(), "sam@example.com", STAFF_PASSWORD).status_code == 401


def test_staff_who_never_completed_didit_verification_cannot_sign_in(app):
    make_staff(verified=False)
    r = sign_in(app.test_client(), "sam@example.com", STAFF_PASSWORD)
    assert r.status_code == 403 and b"setup is incomplete" in r.data


@pytest.mark.parametrize("status,active", [(S.SUSPENDED, False), (S.DEACTIVATED, False), (S.REJECTED, False), (S.PENDING_APPROVAL, True)])
def test_blocked_or_pending_admins_cannot_sign_in(app, make_user, status, active):
    make_admin(make_user, status=status, active=active)
    assert sign_in(app.test_client(), "admin", GOOD_PASSWORD).status_code == 401


# ----------------------------------------------------------------------------- session + CSRF
def test_a_fresh_session_is_started_on_every_successful_sign_in(app, make_user):
    make_admin(make_user)
    make_staff()
    for identifier, password in (("admin", GOOD_PASSWORD), ("sam@example.com", STAFF_PASSWORD)):
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["attacker_planted"] = "yes"
        assert sign_in(c, identifier, password).status_code == 302
        with c.session_transaction() as sess:
            assert "attacker_planted" not in sess and "_user_id" in sess


def test_failed_sign_in_does_not_authenticate_a_planted_session(app, make_user):
    make_admin(make_user)
    c = app.test_client()
    assert sign_in(c, "admin", "Wrong-Password-1!").status_code == 401 and not signed_in(c)


def test_csrf_is_enforced_on_the_login_form():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        c = app.test_client()
        assert c.post("/auth/login", data={"identifier": "admin", "password": "x"}).status_code == 400
        assert c.get("/auth/login").status_code == 200
        db.session.remove()
        db.drop_all()


# ----------------------------------------------------------------------------- legacy pages share the same rules
def test_legacy_staff_page_uses_the_same_rules(app):
    make_staff("w@example.com", status=S.PENDING_APPROVAL)
    make_staff()
    c = app.test_client()
    assert c.post("/staff/login", data={"email": "w@example.com", "password": STAFF_PASSWORD}).status_code == 403
    assert c.post("/staff/login", data={"email": "sam@example.com", "password": STAFF_PASSWORD}).status_code == 302


# ----------------------------------------------------------------------------- Google sign-in is unchanged
def test_google_still_resolves_only_existing_authorized_accounts(app, make_user):
    admin = make_user("owner@example.com", role=Role.ADMIN)
    before = db.session.scalar(db.select(db.func.count(User.id)))
    user, error = google_auth.authorize_google_user({"sub": "g-1", "email": "owner@example.com", "email_verified": True})
    assert error is None and user.id == admin.id and user.role == Role.ADMIN and user.google_sub == "g-1"
    unknown, error = google_auth.authorize_google_user({"sub": "g-2", "email": "stranger@example.com", "email_verified": True})
    assert unknown is None and error
    assert db.session.scalar(db.select(db.func.count(User.id))) == before            # nobody is ever created


def test_google_never_creates_or_promotes_staff_and_can_block_staff_when_switched_off(app, make_user):
    staff = make_staff()
    app.config["STAFF_GOOGLE_LOGIN_ALLOWED"] = False
    user, error = google_auth.authorize_google_user({"sub": "g-3", "email": "sam@example.com", "email_verified": True})
    assert user is None and "Staff Portal" in error
    assert db.session.get(User, staff.id).role == Role.STAFF


@pytest.mark.parametrize("status,active", [(S.PENDING_APPROVAL, True), (S.PENDING_VERIFICATION, True), (S.SUSPENDED, False),
                                           (S.REJECTED, False), (S.DEACTIVATED, False)])
def test_google_rejects_pending_and_blocked_accounts(app, make_user, status, active):
    make_user("owner@example.com", role=Role.ADMIN, status=status, active=active)
    user, error = google_auth.authorize_google_user({"sub": "g-4", "email": "owner@example.com", "email_verified": True})
    assert user is None and error


def test_google_rejects_unverified_google_emails(app, make_user):
    make_user("owner@example.com", role=Role.ADMIN)
    user, error = google_auth.authorize_google_user({"sub": "g-5", "email": "owner@example.com", "email_verified": False})
    assert user is None and error
