"""Staff portal using password login and one-time Didit identity verification.

Sign-in = email + password.
Enrollment = password setup + consent + one-time Didit ID and face verification.
Uses a FAKE provider to test provider outcomes.
"""
import time
import uuid
from datetime import timedelta

import pytest

from app import create_app
from app.auth.services import authorize_google_user
from app.extensions import db
from app.identity import services as idv
from app.models import IdentityVerification, StaffCredential, User
from app.models.staff_credential import utcnow
from app.staff_auth.services import create_staff, deactivate_staff
from werkzeug.security import generate_password_hash
from config import TestingConfig
from tests.identity.conftest import event_rows as idv_events, post_webhook, webhook_body

BIO_WORKFLOW = TestingConfig.DIDIT_BIOMETRIC_WORKFLOW_ID


# ----------------------------------------------------------------------------- helpers
def _row(user_id, purpose):
    db.session.expire_all()
    return db.session.execute(
        db.select(IdentityVerification).filter_by(user_id=user_id, purpose=purpose)
        .order_by(IdentityVerification.id.desc())
    ).scalars().first()


def kyc_row(user_id):
    return _row(user_id, "kyc")


def face_row(user_id):
    return _row(user_id, "biometric_auth")


def credential(user_id):
    db.session.expire_all()
    return db.session.execute(db.select(StaffCredential).filter_by(user_id=user_id)).scalar_one()


@pytest.fixture()
def staff(app):
    """An enrolled staff member with a password and approved ID verification."""
    user, staff_id, _token = create_staff("sam@example.com", "Sam Cruz")

    cred = credential(user.id)
    cred.password_hash = generate_password_hash("CorrectPassword123!")

    db.session.add(IdentityVerification(
        user_id=user.id,
        provider="didit",
        provider_session_id=str(uuid.uuid4()),
        environment="sandbox",
        status="verified",
        purpose="kyc",
        decided_at=utcnow(),
        completed_at=utcnow(),
    ))
    db.session.commit()

    return user, staff_id

def sign_in(client, user, password="CorrectPassword123!"):
    return client.post(
        "/staff/login",
        data={
            "email": user.email,
            "password": password,
        },
    )

def sign_in(client, user, password="CorrectPassword123!"):
    return client.post(
        "/staff/login",
        data={
            "email": user.email,
            "password": password,
        },
    )

def signed_in(client):
    return client.get("/dashboard/").status_code == 200


# ============================================================ the portal fails closed
@pytest.mark.parametrize("override", [
    {"IDV_ENABLED": False},
    {"DIDIT_WORKFLOW_ID": None},
])
def test_enrollment_is_unavailable_without_didit_configuration(override):
    cfg = type("Cfg", (TestingConfig,), override)
    c = create_app(cfg).test_client()

    # Password login should not require the old biometric workflow.
    assert c.get("/staff/login").status_code == 200

    # Enrollment must still require Didit ID verification.
    assert c.get("/staff/enroll/anything").status_code == 503


def test_no_camera_permission_is_requested_any_more(app):
    r = app.test_client().get("/staff/login")
    assert r.status_code == 200
    assert "camera=()" in r.headers.get("Permissions-Policy", "").replace(" ", "")
    assert "media-src" not in r.headers.get("Content-Security-Policy", "")


def test_no_face_data_columns_remain_in_the_models():
    for gone in ("face_id", "face_enrolled_at", "biometric_consent_at"):
        assert not hasattr(StaffCredential, gone)


# ============================================================ onboarding through Didit
def test_full_enrollment_then_sign_in_end_to_end(app, provider):
    user, _staff_id, token = create_staff("new@example.com", "New Person")
    ref = f"laundrix:{user.id}"

    c = app.test_client()

    # Set password and give consent for one-time ID verification.
    assert c.get(f"/staff/enroll/{token}").status_code == 200

    r = c.post(f"/staff/enroll/{token}", data={
        "password": "NewSecurePassword123!",
        "confirm_password": "NewSecurePassword123!",
        "consent": "on",
    })
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/staff/enroll/verify")
    assert c.get("/staff/enroll/verify").status_code == 200

    r = c.post("/staff/enroll/start")
    assert r.status_code == 302
    assert r.headers["Location"].startswith("https://verify.didit.me/")
    assert provider.workflows[-1] is None
    assert provider.callbacks[-1] == (
        app.config["APP_BASE_URL"] + "/staff/enroll/return"
    )

    v = kyc_row(user.id)
    assert v.status == "in_progress"
    assert v.purpose == "kyc"

    # Didit approves the one-time ID and selfie verification.
    post_webhook(c, webhook_body(v, "Approved"))
    r = c.get("/staff/enroll/return")

    assert r.status_code == 302
    assert r.headers["Location"].endswith("/staff/enroll/done")
    assert credential(user.id).enroll_token_hash is None
    assert app.test_client().get(f"/staff/enroll/{token}").status_code == 404

    provider.finish(ref)

    # Normal sign-in now requires only email and password.
    c2 = app.test_client()
    r = sign_in(c2, user, "NewSecurePassword123!")

    assert r.status_code == 302
    assert r.headers["Location"].endswith("/dashboard/")
    assert signed_in(c2)

    # Password login must not create a biometric_auth verification.
    assert face_row(user.id) is None


def test_enrollment_needs_a_valid_password_and_consent(app, provider):
    user, _staff_id, token = create_staff("a@example.com")
    c = app.test_client()

    # Missing consent must prevent enrollment from starting.
    r = c.post(f"/staff/enroll/{token}", data={
        "password": "ValidPassword123!",
        "confirm_password": "ValidPassword123!",
    })
    assert r.status_code == 400

    # Password confirmation must match.
    r = c.post(f"/staff/enroll/{token}", data={
        "password": "ValidPassword123!",
        "confirm_password": "DifferentPassword123!",
        "consent": "on",
    })
    assert r.status_code == 400

    # Password must meet the minimum length.
    r = c.post(f"/staff/enroll/{token}", data={
        "password": "short",
        "confirm_password": "short",
        "consent": "on",
    })
    assert r.status_code == 400

    assert credential(user.id).enroll_token_hash is not None
    assert c.get("/staff/enroll/verify").status_code == 403
    assert c.post("/staff/enroll/start").status_code == 403
    assert provider.calls["create"] == 0


def test_enrollment_rejection_is_retryable_with_the_same_link(app, provider):
    user, _staff_id, token = create_staff("a@example.com")
    c = app.test_client()

    r = c.post(f"/staff/enroll/{token}", data={
        "password": "RetryPassword123!",
        "confirm_password": "RetryPassword123!",
        "consent": "on",
    })
    assert r.status_code == 302

    r = c.post("/staff/enroll/start")
    assert r.status_code == 302

    v = kyc_row(user.id)
    assert v is not None

    post_webhook(c, webhook_body(v, "Declined"))

    r = c.get("/staff/enroll/return")
    assert r.status_code == 302
    assert r.headers["Location"].endswith("/staff/enroll/verify")
    assert credential(user.id).enroll_token_hash is not None

    provider.finish(f"laundrix:{user.id}")

    r = c.post("/staff/enroll/start")
    assert r.status_code == 302
    assert provider.calls["create"] == 2


def test_an_admin_issued_link_lets_an_already_verified_person_reverify(app, provider, staff):
    user, staff_id = staff
    token = __import__("app.staff_auth.services", fromlist=["x"]).new_enroll_link(user)
    c = app.test_client()
    c.post(f"/staff/enroll/{token}", data={"staff_id": staff_id, "consent": "on"})
    r = c.post("/staff/enroll/start")
    assert r.status_code == 302 and provider.calls["create"] == 1   # not blocked as "already verified"


def test_unenrolled_staff_stop_at_step_two(app, provider):
    user, staff_id, _ = create_staff("late@example.com")
    c = app.test_client()
    c.post("/staff/login", data={"email": user.email})
    r = c.post("/staff/verify-id", data={"staff_id": staff_id})
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/login")
    assert provider.calls["create"] == 0 and not signed_in(c)



# ============================================================ sign-in: email and password

def test_unknown_email_cannot_sign_in(app):
    c = app.test_client()

    r = c.post("/staff/login", data={
        "email": "ghost@example.com",
        "password": "SomePassword123!",
    })

    assert r.status_code == 401
    assert not signed_in(c)


def test_locked_accounts_cannot_sign_in(app, staff):
    user, _staff_id = staff
    cred = credential(user.id)
    cred.locked_until = utcnow() + timedelta(minutes=5)
    db.session.commit()

    c = app.test_client()
    r = sign_in(c, user)

    assert r.status_code == 423
    assert not signed_in(c)


def test_repeated_wrong_passwords_lock_the_account(app, staff):
    user, _staff_id = staff
    c = app.test_client()

    for _ in range(5):
        sign_in(c, user, "WrongPassword123!")

    assert credential(user.id).is_locked

    r = sign_in(c, user, "CorrectPassword123!")
    assert r.status_code == 423
    assert not signed_in(c)


def test_deactivated_staff_cannot_sign_in(app, staff):
    user, _staff_id = staff
    deactivate_staff(user)

    c = app.test_client()
    r = sign_in(c, user)

    assert r.status_code == 401
    assert not signed_in(c)


def test_unenrolled_staff_cannot_sign_in(app):
    user, _staff_id, _token = create_staff("late@example.com")

    # This account has no password and no verified ID.
    c = app.test_client()
    r = c.post("/staff/login", data={
        "email": user.email,
        "password": "SomePassword123!",
    })

    assert r.status_code in (401, 403)
    assert not signed_in(c)


# ============================================================ separation from ID verification

def test_staff_cannot_use_google_login_by_default(app):
    create_staff("sam@example.com", "Sam")
    user, error = authorize_google_user({"sub": "g-1", "email": "sam@example.com", "email_verified": True})
    assert user is None and "Staff Portal" in error

def test_staff_can_use_google_login_when_enabled(app):
    create_staff("sam@example.com", "Sam")
    app.config["STAFF_GOOGLE_LOGIN_ALLOWED"] = True

    user, error = authorize_google_user({
        "sub": "g-1",
        "email": "sam@example.com",
        "email_verified": True,
    })

    assert user is not None
    assert user.role == "staff"
    assert error is None

# ============================================================ retention
def test_sign_in_face_check_records_expire_but_a_current_id_verification_stays(app, staff):
    user, _ = staff
    old = utcnow() - timedelta(days=120)

    def row(purpose, updated, sid):
        v = IdentityVerification(user_id=user.id, provider="didit", provider_session_id=sid,
                                 environment="sandbox", status="verified", purpose=purpose, updated_at=updated)
        db.session.add(v); db.session.commit(); return v.id

    old_face = row("biometric_auth", old, "f1")
    new_face = row("biometric_auth", utcnow(), "f2")
    old_kyc = row("kyc", old, "k1")                        # active user's proof of identity

    assert idv.purge_old_records(365, dry_run=True)["matched"] == 1
    idv.purge_old_records(365)
    db.session.expire_all()
    assert db.session.get(IdentityVerification, old_face) is None
    assert db.session.get(IdentityVerification, new_face) is not None
    assert db.session.get(IdentityVerification, old_kyc) is not None


# ============================================================ CLI
def test_cli_commands_and_the_old_face_commands_are_gone(app):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["create-staff", "cli@example.com", "--name", "Cli Person"])
    assert r.exit_code == 0 and "Staff ID" in r.output and "/staff/enroll/" in r.output
    assert "AWS" not in r.output and "Rekognition" not in r.output

    assert "verified=False" in runner.invoke(args=["staff-status", "cli@example.com"]).output
    assert "/staff/enroll/" in runner.invoke(args=["new-enroll-link", "cli@example.com"]).output
    assert "New Staff ID" in runner.invoke(args=["reset-staff", "cli@example.com"]).output

    r = runner.invoke(args=["deactivate-staff", "cli@example.com"])
    assert "Didit" in r.output
    assert not db.session.execute(db.select(User).filter_by(email="cli@example.com")).scalar_one().is_active

    assert runner.invoke(args=["create-staff", "not-an-email"]).exit_code == 1
    assert runner.invoke(args=["face-setup"]).exit_code == 2         # removed along with AWS
