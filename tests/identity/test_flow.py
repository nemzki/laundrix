"""Application-level tests for the identity verification feature, using a FAKE provider.

They prove OUR behaviour for given provider outcomes. They are not evidence that the real Didit
service behaves this way: see tests/integration/test_didit_sandbox.py for that.
"""
import time

import pytest
from markupsafe import escape

from app import create_app
from app.extensions import db
from app.identity import services
from app.identity.provider.base import (
    ProviderAuthError, ProviderRateLimited, ProviderUnavailable,
)
from app.identity.statuses import CATEGORY_HINTS
from app.models import IdentityVerification, Role
from config import TestingConfig
from tests.identity.conftest import (
    event_rows, latest, login, post_webhook, start, warning, webhook_body,
)


def page(client):
    return client.get("/identity/").get_data(as_text=True)


def started(client, user):
    assert start(client).status_code == 302
    return latest(user.id)


# ================================================================ feature switch / access
def test_feature_is_404_when_disabled():
    class Off(TestingConfig):
        IDV_ENABLED = False
    app = create_app(Off)
    c = app.test_client()
    assert c.get("/identity/").status_code == 404
    assert c.post("/identity/webhook/didit", json={}).status_code == 404


def test_pages_require_login(app):
    c = app.test_client()
    for path in ("/identity/", "/identity/start", "/identity/return"):
        r = c.get(path)
        assert r.status_code == 302 and "/auth/login" in r.headers["Location"], path
    assert c.post("/identity/refresh").status_code == 302


def test_secrets_never_appear_in_pages(client, app):
    start(client)
    for body in (page(client), client.get("/identity/start").get_data(as_text=True)):
        assert app.config["DIDIT_API_KEY"] not in body
        assert app.config["DIDIT_WEBHOOK_SECRET"] not in body


# ================================================================ starting
def test_consent_is_required_before_any_provider_call(client, user, provider):
    r = start(client, consent=False)
    assert r.status_code == 302 and r.headers["Location"].endswith("/identity/start")
    assert provider.calls["create"] == 0
    assert latest(user.id) is None


def test_start_creates_a_session_and_redirects_to_the_hosted_page(client, user, provider, app):
    r = start(client)
    assert r.status_code == 302
    assert r.headers["Location"].startswith("https://verify.didit.me/")
    v = latest(user.id)
    assert (v.status, v.environment, v.provider) == ("in_progress", "sandbox", "didit")
    assert v.consent_version and v.consent_at and v.provider_session_id
    assert provider.user_refs == [f"laundrix:{user.id}"]
    assert provider.callbacks[0] == app.config["APP_BASE_URL"] + "/identity/return"


def test_clicking_start_twice_resumes_the_same_attempt(client, user, provider):
    first = started(client, user)
    start(client)
    assert db.session.query(IdentityVerification).filter_by(user_id=user.id).count() == 1
    assert latest(user.id).id == first.id


# ================================================================ outcomes
def test_successful_verification_and_no_personal_data_is_stored(client, user, app):
    v = started(client, user)
    decision = {
        "status": "Approved",
        "id_verifications": [{
            "document_type": "Passport", "document_number": "P1234567A", "first_name": "Juan",
            "last_name": "Dela Cruz", "date_of_birth": "1990-01-01", "warnings": [],
        }],
        "face_matches": [{"score": 96.1, "status": "Approved", "warnings": []}],
    }
    r = post_webhook(client, webhook_body(v, "Approved", decision=decision))
    assert r.status_code == 200
    v = latest(user.id)
    assert v.status == "verified" and v.decided_at and v.document_type == "Passport"
    assert "Your identity is verified" in page(client)

    # privacy: nothing identifying was persisted anywhere
    stored = repr([getattr(v, c.name) for c in v.__table__.columns])
    stored += repr([[getattr(e, c.name) for c in e.__table__.columns] for e in event_rows(v.id)])
    for secret in ("P1234567A", "Juan", "Dela Cruz", "1990-01-01", "96.1"):
        assert secret not in stored


@pytest.mark.parametrize("code, category", [
    ("DOCUMENT_TYPE_NOT_SUPPORTED", "document"),   # test-only illustrative code
    ("DOCUMENT_EXPIRED", "document_expired"),      # documented by the provider
    ("LOW_FACE_MATCH_SIMILARITY", "face"),         # documented by the provider
    ("LIVENESS_CHECK_FAILED", "face"),             # test-only illustrative code
])
def test_declined_outcomes_reject_with_a_generic_hint_and_hide_internal_codes(client, user, code, category):
    v = started(client, user)
    decision = {"status": "Declined", "id_verifications": [{"warnings": [warning(code)]}]}
    post_webhook(client, webhook_body(v, "Declined", decision=decision))
    v = latest(user.id)
    assert v.status == "rejected" and v.reason_codes == [code]
    body = page(client)
    assert str(escape(CATEGORY_HINTS[category])) in body
    assert code not in body                      # raw internal codes never reach the user
    assert "Not verified" in body                # the status badge for a rejection


def test_poor_image_quality_resubmission_means_action_required_not_rejected(client, user):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "Resubmitted"))
    assert latest(user.id).status == "action_required"
    assert "Action needed" in page(client)


def test_manual_review_then_approval(client, user):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "In Review", created_at=int(time.time())))
    assert latest(user.id).status == "pending_review"
    assert "reviewing" in page(client)
    post_webhook(client, webhook_body(v, "Approved", created_at=int(time.time()) + 5))
    assert latest(user.id).status == "verified"


def test_pending_review_blocks_a_new_attempt(client, user, provider):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "In Review"))
    start(client)
    assert provider.calls["create"] == 1


def test_expired_session_can_be_restarted(client, user, provider):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "Expired"))
    assert latest(user.id).status == "action_required"
    provider.finish(f"laundrix:{user.id}")
    start(client)
    assert provider.calls["create"] == 2
    assert latest(user.id).id != v.id and latest(user.id).status == "in_progress"


def test_a_verified_user_cannot_start_again_nor_be_downgraded_by_a_late_event(client, user, provider):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "Approved", created_at=100))
    post_webhook(client, webhook_body(v, "Declined", created_at=200))  # correctly signed, but illegal
    assert latest(user.id).status == "verified"
    assert event_rows(v.id)[-1].outcome == "invalid_transition"
    start(client)
    assert provider.calls["create"] == 1


def test_approval_expiry_requires_reverification(client, user, provider):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "Approved", created_at=100))
    post_webhook(client, webhook_body(v, "Kyc Expired", created_at=200))
    assert latest(user.id).status == "action_required"


# ================================================================ provider failures
@pytest.mark.parametrize("error", [
    ProviderAuthError("bad key"), ProviderUnavailable("timeout"), ProviderRateLimited(retry_after=30),
])
def test_provider_failure_is_an_error_status_never_a_rejection(client, user, provider, error):
    provider.create_error = error
    r = start(client)
    assert r.status_code == 302 and "/identity/" in r.headers["Location"]
    v = latest(user.id)
    assert v.status == "error" and v.error_code == error.code and v.provider_session_id is None
    body = page(client)
    assert "Something went wrong on our side" in body and "Try again" in body
    assert services.attempts_in_window(user) == 0          # does not burn the user's retries

    provider.create_error = None                           # provider recovers
    start(client)
    assert latest(user.id).status == "in_progress"


def test_repeated_provider_failures_do_not_pile_up_rows(client, user, provider):
    provider.create_error = ProviderUnavailable("down")
    for _ in range(4):
        start(client)
    assert db.session.query(IdentityVerification).filter_by(user_id=user.id).count() == 1


def test_provider_failure_never_disturbs_an_open_attempt(client, user, provider):
    v = started(client, user)
    provider.create_error = ProviderUnavailable("timeout")
    start(client)
    assert latest(user.id).id == v.id and latest(user.id).status == "in_progress"


# ================================================================ polling / return page
def test_refresh_applies_the_authoritative_decision(client, user, provider):
    started(client, user)
    provider.decision_status = "Approved"
    client.post("/identity/refresh")
    assert latest(user.id).status == "verified"
    assert event_rows(latest(user.id).id)[-1].source == "poll"


def test_id_verification_can_resume_after_a_reviewer_asks_for_a_resubmission(client, user, provider):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "Resubmitted"))
    assert latest(user.id).status == "action_required"
    provider.decision_status = "In Progress"             # the person is redoing the step in the same session
    client.post("/identity/refresh")
    assert latest(user.id).status == "in_progress"


def test_refresh_when_provider_is_down_changes_nothing(client, user, provider):
    started(client, user)
    provider.decision_error = ProviderUnavailable("down")
    client.post("/identity/refresh")
    assert latest(user.id).status == "in_progress"


def test_refresh_is_throttled_by_a_cooldown(client, user, provider):
    started(client, user)
    client.post("/identity/refresh")
    client.post("/identity/refresh")
    assert provider.calls["decision"] == 1


def test_return_page_ignores_attacker_controlled_query_params(client, user, provider):
    v = started(client, user)
    r = client.get(f"/identity/return?status=Approved&verificationSessionId={v.provider_session_id}")
    assert r.status_code == 302
    assert latest(user.id).status == "in_progress"       # provider (fake) still says In Progress


# ================================================================ webhook security
def test_invalid_signature_is_rejected_and_changes_nothing(client, user):
    v = started(client, user)
    r = post_webhook(client, webhook_body(v, "Approved"), signature="0" * 64)
    assert r.status_code == 401 and latest(user.id).status == "in_progress"


def test_wrong_secret_is_rejected(client, user):
    v = started(client, user)
    r = post_webhook(client, webhook_body(v, "Approved"), secret="not-the-secret")
    assert r.status_code == 401 and latest(user.id).status == "in_progress"


def test_body_tampered_after_signing_is_rejected(client, user):
    v = started(client, user)
    body = webhook_body(v, "Declined")
    from app.identity.signature import compute_signature_v2
    sig = compute_signature_v2(body, "test-webhook-secret")
    body["status"] = "Approved"                            # attacker flips the verdict
    r = post_webhook(client, body, signature=sig)
    assert r.status_code == 401 and latest(user.id).status == "in_progress"


def test_missing_headers_and_stale_timestamps_are_rejected(client, user):
    v = started(client, user)
    body = webhook_body(v, "Approved")
    assert post_webhook(client, body, signature="").status_code == 401
    assert post_webhook(client, body, timestamp=str(int(time.time()) - 1000)).status_code == 401
    old = webhook_body(v, "Approved")
    old["timestamp"] = int(time.time()) - 1000            # replay: old signed body + forged fresh header
    assert post_webhook(client, old).status_code == 401
    assert latest(user.id).status == "in_progress"


def test_malformed_json_is_a_400(client):
    assert post_webhook(client, {}, raw="not json").status_code == 400


def test_duplicate_event_is_applied_once(client, user):
    v = started(client, user)
    body = webhook_body(v, "Approved", event_id="evt-1")
    assert post_webhook(client, body).status_code == 200
    n = len(event_rows(v.id))
    assert post_webhook(client, body).status_code == 200
    assert len(event_rows(v.id)) == n
    assert [e.event_id for e in event_rows(v.id)].count("evt-1") == 1


def test_out_of_order_older_event_is_ignored_as_stale(client, user):
    v = started(client, user)
    post_webhook(client, webhook_body(v, "In Review", created_at=2000))
    post_webhook(client, webhook_body(v, "In Progress", created_at=1000))
    assert latest(user.id).status == "pending_review"
    assert event_rows(v.id)[-1].outcome == "stale"


@pytest.mark.parametrize("override", [
    {"environment": "live"},                       # sandbox deployment must ignore live events
    {"vendor_data": "laundrix:99999"},             # session does not belong to that vendor ref
    {"session_id": "00000000-0000-0000-0000-000000000000"},  # unknown session
    {"webhook_type": "data.updated"},              # not a status event
])
def test_events_that_do_not_match_us_are_acknowledged_but_never_applied(client, user, override):
    v = started(client, user)
    r = post_webhook(client, webhook_body(v, "Approved", **override))
    assert r.status_code == 200
    assert latest(user.id).status == "in_progress"


def test_console_test_deliveries_are_acknowledged_but_never_applied(client, user):
    v = started(client, user)
    r = post_webhook(client, webhook_body(v, "Approved"), headers={"X-Didit-Test-Webhook": "true"})
    assert r.status_code == 200 and latest(user.id).status == "in_progress"


def test_webhook_works_without_csrf_token_but_user_forms_need_one():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True
    app = create_app(CsrfOn)
    from tests.identity.fakes import FakeProvider
    app.extensions["idv_provider"] = FakeProvider()
    with app.app_context():
        db.create_all()
        from app.models import User
        u = User(email="c@example.com", role=Role.STAFF, is_active=True)
        db.session.add(u); db.session.commit()
        c = app.test_client(); app.config["SESSION_PROTECTION"] = None; app.login_manager.session_protection = None
        login(c, u)
        assert c.post("/identity/start", data={"consent": "on"}).status_code == 400   # no CSRF token
        # the webhook is exempt from CSRF; it is protected by the HMAC signature instead
        assert c.post("/identity/webhook/didit", json={}).status_code == 401
        db.session.remove(); db.drop_all()


# ================================================================ authorization
def test_users_cannot_see_or_touch_each_others_records(app, make_user, provider):
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    ca, cb = app.test_client(), app.test_client()
    login(ca, alice); login(cb, bob)

    va = started(ca, alice)
    assert ca.get(f"/identity/attempt/{va.public_id}").status_code == 200
    assert cb.get(f"/identity/attempt/{va.public_id}").status_code == 404   # not even "forbidden"

    assert "Start verification" in page(cb)                                  # bob sees his own state
    cb.post("/identity/refresh")                                             # nothing of bob's to poll
    assert provider.calls["decision"] == 0
    assert latest(alice.id).status == "in_progress"


def test_a_webhook_for_one_user_cannot_change_another(app, make_user):
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    ca, cb = app.test_client(), app.test_client()
    login(ca, alice); login(cb, bob)
    va = started(ca, alice); vb = started(cb, bob)
    post_webhook(ca, webhook_body(va, "Approved"))
    assert latest(alice.id).status == "verified" and latest(bob.id).status == "in_progress"
    # bob's session id paired with alice's vendor ref must be refused
    post_webhook(ca, webhook_body(vb, "Approved", vendor_data=f"laundrix:{alice.id}"))
    assert latest(bob.id).status == "in_progress"


# ================================================================ retry limits
def test_attempt_limit_blocks_further_attempts_but_provider_errors_do_not_count(app, client, user, provider):
    app.config["IDV_MAX_ATTEMPTS"] = 2
    ref = f"laundrix:{user.id}"
    for _ in range(2):
        v = started(client, user)
        post_webhook(client, webhook_body(v, "Declined"))
        provider.finish(ref)
    start(client)                                           # third attempt
    assert provider.calls["create"] == 2
    assert "limit of verification attempts" in page(client)


def test_provider_errors_do_not_consume_attempts(app, client, user, provider):
    app.config["IDV_MAX_ATTEMPTS"] = 1
    provider.create_error = ProviderUnavailable("x")
    for _ in range(3):
        start(client)
    provider.create_error = None
    start(client)
    assert latest(user.id).status == "in_progress"


# ================================================================ retention
def test_purge_removes_old_non_verified_records_only(app, user, make_user):
    from datetime import timedelta
    from app.models.staff_credential import utcnow
    old = utcnow() - timedelta(days=400)

    def row(status, updated_at, u=user, sid=None):
        v = IdentityVerification(user_id=u.id, provider="didit", environment="sandbox",
                                 status=status, provider_session_id=sid, updated_at=updated_at)
        db.session.add(v); db.session.commit(); return v.id

    old_rejected = row("rejected", old, sid="s1")
    recent_rejected = row("rejected", utcnow(), sid="s2")
    old_verified = row("verified", old, sid="s3")
    gone = make_user("gone@example.com", active=False)
    old_verified_inactive = row("verified", old, u=gone, sid="s4")

    dry = services.purge_old_records(365, dry_run=True)
    assert dry["matched"] == 2 and db.session.get(IdentityVerification, old_rejected)

    services.purge_old_records(365)
    db.session.expire_all()
    assert db.session.get(IdentityVerification, old_rejected) is None
    assert db.session.get(IdentityVerification, old_verified_inactive) is None
    assert db.session.get(IdentityVerification, recent_rejected) is not None
    assert db.session.get(IdentityVerification, old_verified) is not None   # active user's proof is kept
