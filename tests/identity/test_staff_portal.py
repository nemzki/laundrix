"""Staff portal after the move from AWS Rekognition to Didit.

Sign-in = email + Staff ID + a live face check done by Didit (Biometric Authentication).
Uses a FAKE provider: these prove how Laundrix reacts to given provider outcomes, not how the real
Didit service behaves (see tests/integration for that).
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
    """An already-enrolled staff member (their one-time ID verification was approved)."""
    user, staff_id, _token = create_staff("sam@example.com", "Sam Cruz")
    db.session.add(IdentityVerification(
        user_id=user.id, provider="didit", provider_session_id=str(uuid.uuid4()),
        environment="sandbox", status="verified", purpose="kyc",
        decided_at=utcnow(), completed_at=utcnow(),
    ))
    db.session.commit()
    return user, staff_id


def to_face_step(client, user, staff_id):
    assert client.post("/staff/login", data={"email": user.email}).status_code == 302
    r = client.post("/staff/verify-id", data={"staff_id": staff_id})
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-face")


def start_face(client):
    r = client.post("/staff/verify-face/start")
    assert r.status_code == 302 and r.headers["Location"].startswith("https://verify.didit.me/")
    return r


def signed_in(client):
    return client.get("/dashboard/").status_code == 200


# ============================================================ the portal fails closed
@pytest.mark.parametrize("override", [
    {"IDV_ENABLED": False},
    {"DIDIT_BIOMETRIC_WORKFLOW_ID": None},
])
def test_portal_is_unavailable_until_didit_is_configured(override):
    cfg = type("Cfg", (TestingConfig,), override)
    c = create_app(cfg).test_client()
    for path in ("/staff/login", "/staff/verify-id", "/staff/enroll/anything"):
        assert c.get(path).status_code == 503, path


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
    user, staff_id, token = create_staff("new@example.com", "New Person")
    ref = f"laundrix:{user.id}"

    # ---- onboarding (one time): consent + Staff ID -> Didit ID verification -> done
    c = app.test_client()
    assert c.get(f"/staff/enroll/{token}").status_code == 200
    r = c.post(f"/staff/enroll/{token}", data={"staff_id": staff_id, "consent": "on"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/enroll/verify")
    assert c.get("/staff/enroll/verify").status_code == 200

    r = c.post("/staff/enroll/start")
    assert r.status_code == 302 and r.headers["Location"].startswith("https://verify.didit.me/")
    assert provider.workflows[-1] is None                       # default ID-verification workflow
    assert provider.callbacks[-1] == app.config["APP_BASE_URL"] + "/staff/enroll/return"
    v = kyc_row(user.id)
    assert v.status == "in_progress" and v.purpose == "kyc"

    post_webhook(c, webhook_body(v, "Approved"))                  # Didit approves the ID + selfie
    r = c.get("/staff/enroll/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/enroll/done")
    assert credential(user.id).enroll_token_hash is None          # link is now dead
    assert app.test_client().get(f"/staff/enroll/{token}").status_code == 404
    provider.finish(ref)

    # ---- every sign-in: email -> Staff ID -> Didit face check
    c2 = app.test_client()
    to_face_step(c2, user, staff_id)
    assert c2.get("/staff/verify-face").status_code == 200
    start_face(c2)
    assert provider.workflows[-1] == BIO_WORKFLOW                 # the Biometric Authentication workflow
    assert provider.user_refs[-1] == ref                          # same person reference -> stored portrait
    assert provider.callbacks[-1] == app.config["APP_BASE_URL"] + "/staff/verify-face/return"
    f = face_row(user.id)
    assert f.status == "in_progress" and f.purpose == "biometric_auth"
    assert not signed_in(c2)                                      # not signed in until the check passes

    post_webhook(c2, webhook_body(f, "Approved"))
    r = c2.get("/staff/verify-face/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/")
    assert signed_in(c2)
    assert credential(user.id).last_verified_at is not None


def test_enrollment_needs_the_staff_id_and_the_consent_box(app, provider):
    user, staff_id, token = create_staff("a@example.com")
    c = app.test_client()
    assert c.post(f"/staff/enroll/{token}", data={"staff_id": "WRONG-ID", "consent": "on"}).status_code == 401
    assert credential(user.id).failed_attempts == 1
    assert c.post(f"/staff/enroll/{token}", data={"staff_id": staff_id}).status_code == 400
    assert c.get("/staff/enroll/verify").status_code == 403       # no session yet
    assert c.post("/staff/enroll/start").status_code == 403
    assert provider.calls["create"] == 0


def test_enrollment_rejection_is_retryable_with_the_same_link(app, provider):
    user, staff_id, token = create_staff("a@example.com")
    c = app.test_client()
    c.post(f"/staff/enroll/{token}", data={"staff_id": staff_id, "consent": "on"})
    c.post("/staff/enroll/start")
    v = kyc_row(user.id)
    post_webhook(c, webhook_body(v, "Declined"))
    r = c.get("/staff/enroll/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/enroll/verify")
    assert credential(user.id).enroll_token_hash is not None     # link still usable
    provider.finish(f"laundrix:{user.id}")
    assert c.post("/staff/enroll/start").status_code == 302 and provider.calls["create"] == 2


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


# ============================================================ sign-in: the three steps
def test_unknown_email_gets_the_same_flow_and_then_fails(app):
    c = app.test_client()
    r = c.post("/staff/login", data={"email": "ghost@example.com"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-id")
    assert c.post("/staff/verify-id", data={"staff_id": "LX-00000000"}).status_code == 401


def test_the_face_step_cannot_be_reached_without_the_staff_id_step(app, provider, staff):
    user, _ = staff
    c = app.test_client()
    c.post("/staff/login", data={"email": user.email})            # stage is still "id"
    assert c.get("/staff/verify-face").status_code == 302
    assert c.post("/staff/verify-face/start").status_code == 302
    assert provider.calls["create"] == 0


def test_locked_accounts_never_reach_didit(app, provider, staff):
    user, staff_id = staff
    cred = credential(user.id)
    cred.locked_until = utcnow() + timedelta(minutes=5)
    db.session.commit()
    c = app.test_client()
    c.post("/staff/login", data={"email": user.email})
    r = c.post("/staff/verify-id", data={"staff_id": staff_id})   # right ID, still locked out
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/login")
    assert provider.calls["create"] == 0


def test_repeated_wrong_ids_lock_the_account(app, staff):
    user, _ = staff
    c = app.test_client()
    for _ in range(5):
        c.post("/staff/login", data={"email": user.email})
        c.post("/staff/verify-id", data={"staff_id": "WRONG-ID"})
    assert credential(user.id).is_locked


def test_deactivated_staff_cannot_sign_in(app, provider, staff):
    user, staff_id = staff
    deactivate_staff(user)
    c = app.test_client()
    c.post("/staff/login", data={"email": user.email})
    assert c.post("/staff/verify-id", data={"staff_id": staff_id}).status_code == 401


# ============================================================ sign-in: the face check outcomes
def test_a_face_that_does_not_match_counts_as_a_failure_and_ends_after_three(app, provider, staff):
    user, staff_id = staff
    ref = f"laundrix:{user.id}"
    c = app.test_client()
    to_face_step(c, user, staff_id)
    for n in (1, 2, 3):
        start_face(c)
        post_webhook(c, webhook_body(face_row(user.id), "Declined"))
        r = c.get("/staff/verify-face/return")
        assert r.status_code == 302
        provider.finish(ref)
        expected_end = "/staff/login" if n == 3 else "/staff/verify-face"
        assert r.headers["Location"].endswith(expected_end), n
    assert credential(user.id).failed_attempts == 3
    assert not signed_in(c)


def test_an_abandoned_face_check_is_not_a_failed_match(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    post_webhook(c, webhook_body(face_row(user.id), "Abandoned"))
    r = c.get("/staff/verify-face/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-face")
    assert credential(user.id).failed_attempts == 0 and not signed_in(c)


def test_a_provider_outage_is_never_counted_as_a_failed_face(app, provider, staff):
    from app.identity.provider.base import ProviderUnavailable
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    provider.create_error = ProviderUnavailable("down")
    r = c.post("/staff/verify-face/start")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-face")
    assert credential(user.id).failed_attempts == 0 and face_row(user.id) is None
    provider.create_error = None
    start_face(c)                                                  # recovers


def test_a_finished_sign_in_check_is_never_polled_or_reopened(app, provider, staff):
    """Regression: polling used to flip an abandoned check back to in_progress, which also let it
    skip the hourly cost cap."""
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    post_webhook(c, webhook_body(face_row(user.id), "Abandoned"))
    provider.decision_status = "In Progress"            # a (contradictory) provider answer
    polls_before = provider.calls["decision"]
    c.get("/staff/verify-face/return")
    assert provider.calls["decision"] == polls_before     # not even asked
    assert face_row(user.id).status == "action_required"


def test_a_late_in_progress_event_cannot_reopen_an_abandoned_sign_in_check(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    f = face_row(user.id)
    now = int(time.time())
    post_webhook(c, webhook_body(f, "Abandoned", created_at=now))
    post_webhook(c, webhook_body(f, "In Progress", created_at=now + 60))   # newer, correctly signed
    assert face_row(user.id).status == "action_required"
    assert idv_events(f.id)[-1].outcome == "invalid_transition"


def test_the_result_is_picked_up_by_polling_when_no_webhook_arrives(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    provider.decision_status = "Approved"                          # only the API says so
    r = c.get("/staff/verify-face/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard/")
    assert signed_in(c)


def test_the_waiting_page_refreshes_then_gives_up(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    for _ in range(25):
        r = c.get("/staff/verify-face/return")
        assert r.status_code == 200 and b'http-equiv="refresh"' in r.data
    r = c.get("/staff/verify-face/return")                          # one too many
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-face")
    assert not signed_in(c)


def test_attacker_controlled_query_parameters_cannot_sign_anyone_in(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    sid = face_row(user.id).provider_session_id
    r = c.get(f"/staff/verify-face/return?status=Approved&verificationSessionId={sid}")
    assert r.status_code == 200 and not signed_in(c)                # still just "checking"


def test_an_approval_older_than_this_sign_in_is_refused(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    f = face_row(user.id)
    f.status, f.decided_at = "verified", utcnow() - timedelta(hours=1)   # stale approval
    db.session.commit()
    r = c.get("/staff/verify-face/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/login")
    assert not signed_in(c)


def test_someone_elses_approved_face_check_cannot_be_borrowed(app, provider, staff, make_user):
    alice, alice_id = staff
    bob, bob_id, _ = create_staff("bob@example.com")
    db.session.add(IdentityVerification(
        user_id=bob.id, provider="didit", provider_session_id=str(uuid.uuid4()), environment="sandbox",
        status="verified", purpose="kyc", decided_at=utcnow()))
    db.session.commit()

    ca, cb = app.test_client(), app.test_client()
    to_face_step(ca, alice, alice_id); start_face(ca)
    post_webhook(ca, webhook_body(face_row(alice.id), "Approved"))   # alice's own approved check

    to_face_step(cb, bob, bob_id)
    with cb.session_transaction() as s:                             # bob points his wizard at alice's row
        w = s["staff_login"]; w["vid"] = face_row(alice.id).id; s["staff_login"] = w
    r = cb.get("/staff/verify-face/return")
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/verify-face")
    assert not signed_in(cb)


def test_cost_abuse_is_capped_per_person_per_hour(app, provider, staff):
    app.config["IDV_BIOMETRIC_MAX_PER_HOUR"] = 2
    user, staff_id = staff
    ref = f"laundrix:{user.id}"
    c = app.test_client()
    to_face_step(c, user, staff_id)
    for _ in range(2):
        start_face(c)
        post_webhook(c, webhook_body(face_row(user.id), "Abandoned"))
        c.get("/staff/verify-face/return")
        provider.finish(ref)
    before = provider.calls["create"]
    r = c.post("/staff/verify-face/start")                           # a third session
    assert r.status_code == 302 and "didit.me" not in r.headers["Location"]
    assert provider.calls["create"] == before


# ============================================================ separation from ID verification
def test_face_checks_never_show_up_as_the_id_verification_status(app, provider, staff):
    user, staff_id = staff
    c = app.test_client()
    to_face_step(c, user, staff_id)
    start_face(c)
    assert idv.latest_verification(user).purpose == "kyc"
    assert len(idv.history_for(user)) == 1
    assert len(idv.history_for(user, purpose=None)) == 2


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
