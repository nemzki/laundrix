"""Staff Management: the admin-only module, the staff lifecycle and its audit trail."""
import json
import re
import uuid

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.identity import services as idv
from app.models import AccountStatus, AuthEvent, IdentityVerification, Role, StaffCredential, User
from app.models.staff_credential import utcnow
from app.staff_admin import services
from app.staff_admin.services import ActionError
from app.staff_auth.services import create_staff, find_credential_by_token
from config import TestingConfig
from tests.identity.conftest import post_webhook, webhook_body
from tests.laundry.conftest import _login, _make_app
from tests.staffmgmt.conftest import STAFF_PASSWORD

S = AccountStatus


# ----------------------------------------------------------------------------- helpers
def make_staff(email="sam@example.com", status=S.ACTIVE, verified=True, active=True, name="Sam Cruz"):
    user, _sid, token = create_staff(email, name, account_status=status)
    user.staff_credential.password_hash = generate_password_hash(STAFF_PASSWORD)
    user.is_active = active
    if verified:
        db.session.add(IdentityVerification(
            user_id=user.id, provider="didit", provider_session_id=str(uuid.uuid4()), environment="sandbox",
            status="verified", purpose="kyc", decided_at=utcnow(), completed_at=utcnow()))
    db.session.commit()
    return user


def post_new(client, name="Sam Cruz", email="sam@example.com"):
    return client.post("/admin/staff/new", data={"full_name": name, "email": email})


def token_in(response):
    return re.search(r"/staff/enroll/([\w-]+)", response.get_data(as_text=True)).group(1)


def staff_row(email):
    db.session.expire_all()
    return db.session.execute(db.select(User).filter_by(email=email)).scalar_one()


def events(name):
    db.session.expire_all()
    return db.session.scalars(db.select(AuthEvent).filter_by(event=name)).all()


def act(client, user, action, **data):
    return client.post(f"/admin/staff/{user.id}/{action}", data=data, follow_redirects=True)


def html(client, url):
    r = client.get(url)
    assert r.status_code == 200, (url, r.status_code)
    return r.get_data(as_text=True)


# ----------------------------------------------------------------------------- access control
def test_admin_can_open_staff_management(admin_client):
    user = make_staff(status=S.PENDING_VERIFICATION, verified=False)
    page = html(admin_client, "/admin/staff/")
    for text in ("Staff Management", "Loading Staff Management", "staff-loader.js", "Sam Cruz", "sam@example.com"):
        assert text in page, text
    payload = re.search(r'<script type="application/json" id="laundrix-staff-data">(.*?)</script>', page, re.S)
    assert payload is not None
    data = json.loads(payload.group(1))
    row = next(row for row in data['rows'] if row['id'] == user.id)
    assert row['status'] == S.PENDING_VERIFICATION
    assert data['counts']['total'] == 1
    assert data['counts'][S.PENDING_VERIFICATION] == 1
    assert {item['value'] for item in data['filters']} == {'', *S.ALL}
    assert 'staff-boot-skeleton' in page and 'data-staff-fallback' not in page
    assert "Add staff" in html(admin_client, "/admin/staff/new")
    assert "Sam Cruz" in html(admin_client, f"/admin/staff/{user.id}")


def test_navigation_entry_is_admin_only(admin_client, make_user, client_for):
    assert 'href="/admin/staff/"' in html(admin_client, "/orders/")
    staff = client_for(make_user("s@example.com"))
    page = html(staff, "/orders/")
    assert "Staff Management" not in page and "/admin/staff" not in page


def test_staff_and_anonymous_users_cannot_reach_any_staff_management_route(app, make_user, client_for):
    staff = client_for(make_user("s@example.com"))
    anon = app.test_client()
    seen = 0
    for rule in app.url_map.iter_rules():
        if not rule.endpoint.startswith("staff_admin.") or rule.endpoint == "staff_admin.static":
            continue
        seen += 1
        url = re.sub(r"<[^>]+>", "1", rule.rule)
        verb = "get" if "GET" in rule.methods else "post"
        assert getattr(staff, verb)(url).status_code == 403, rule.endpoint
        assert getattr(anon, verb)(url).status_code == 302, rule.endpoint
    assert seen >= 9


@pytest.mark.parametrize("status", AccountStatus.PENDING)
def test_unapproved_staff_cannot_reach_staff_management(make_user, client_for, status):
    r = client_for(make_user("p@example.com", status=status)).get("/admin/staff/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/identity/")


# ----------------------------------------------------------------------------- creating accounts
def test_creating_a_staff_account_issues_a_one_time_enrollment_link(app, admin_client, admin):
    r = post_new(admin_client)
    assert r.status_code == 200
    assert "no-store" in r.headers["Cache-Control"]                     # the secret page is never cached
    token = token_in(r)
    page = r.get_data(as_text=True)
    assert app.config["APP_BASE_URL"] + "/staff/enroll/" + token in page
    assert "Copy link" in page and "only once" in page and "expires" in page

    user = staff_row("sam@example.com")
    assert (user.role, user.account_status, user.is_active, user.full_name) == (Role.STAFF, S.PENDING_VERIFICATION, True, "Sam Cruz")
    cred = user.staff_credential
    assert cred.enroll_token_hash and cred.enroll_token_hash != token   # only a hash is stored
    assert find_credential_by_token(token).user_id == user.id

    # never shown again
    assert token not in html(admin_client, f"/admin/staff/{user.id}") and token not in html(admin_client, "/admin/staff/")
    assert "Active until" in html(admin_client, f"/admin/staff/{user.id}")

    (event,) = events("staff_created")
    assert (event.user_id, event.target_user_id) == (admin.id, user.id) and token not in (event.detail or "")


@pytest.mark.parametrize("name,email", [("", "a@example.com"), ("A", "a@example.com"), ("Ann Lee", "not-an-email"), ("Ann Lee", "")])
def test_invalid_input_creates_nothing(admin_client, name, email):
    r = post_new(admin_client, name, email)
    assert r.status_code == 422 and b"alert-error" in r.data
    assert db.session.scalar(db.select(db.func.count(User.id)).filter_by(role=Role.STAFF)) == 0


def test_duplicate_email_is_refused(admin_client):
    post_new(admin_client)
    assert post_new(admin_client).status_code == 422
    assert db.session.scalar(db.select(db.func.count(User.id)).filter_by(role=Role.STAFF)) == 1


def test_invalid_and_expired_links_are_rejected(app, admin_client):
    token = token_in(post_new(admin_client))
    anon = app.test_client()
    assert anon.get(f"/staff/enroll/{token}").status_code == 200
    assert anon.get("/staff/enroll/not-a-real-token").status_code == 404
    cred = db.session.execute(db.select(StaffCredential)).scalar_one()
    cred.enroll_token_expires_at = utcnow().replace(year=2000)
    db.session.commit()
    assert find_credential_by_token(token) is None
    assert app.test_client().get(f"/staff/enroll/{token}").status_code == 404


def test_a_replacement_link_revokes_the_old_one(app, admin_client):
    old = token_in(post_new(admin_client))
    user = staff_row("sam@example.com")
    r = admin_client.post(f"/admin/staff/{user.id}/enroll-link")
    assert r.status_code == 200 and "no-store" in r.headers["Cache-Control"]
    new = token_in(r)
    assert new != old and find_credential_by_token(old) is None and find_credential_by_token(new) is not None
    (event,) = events("staff_enroll_link_issued")
    assert new not in (event.detail or "") and event.target_user_id == user.id


def test_replacement_links_are_not_offered_for_blocked_accounts(admin_client):
    for status, active in ((S.SUSPENDED, False), (S.REJECTED, False), (S.DEACTIVATED, False), (S.PENDING_APPROVAL, True)):
        user = make_staff(f"{status}@example.com", status=status, active=active)
        r = admin_client.post(f"/admin/staff/{user.id}/enroll-link", follow_redirects=True)
        assert b"can only be issued" in r.data, status


# ----------------------------------------------------------------------------- the real lifecycle
def test_full_lifecycle_through_didit_and_approval(app, admin_client, admin, provider):
    # 1. admin creates the account and sends the link
    token = token_in(post_new(admin_client))
    user = staff_row("sam@example.com")

    # 2. staff sets a password, consents and completes Didit verification
    c = app.test_client()
    assert c.post(f"/staff/enroll/{token}", data={"password": STAFF_PASSWORD, "confirm_password": STAFF_PASSWORD,
                                                 "consent": "on"}).status_code == 302
    assert c.post("/staff/enroll/start").status_code == 302
    db.session.expire_all()
    v = db.session.execute(db.select(IdentityVerification).filter_by(user_id=user.id)).scalars().first()
    post_webhook(c, webhook_body(v, "Approved"))
    assert c.get("/staff/enroll/return").status_code == 302

    # 3. the account now waits for an administrator
    assert staff_row("sam@example.com").account_status == S.PENDING_APPROVAL
    assert "Pending approval" in html(admin_client, "/admin/staff/?status=pending_approval")
    assert len(events("staff_verification_completed")) == 1
    blocked = app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD})
    assert blocked.status_code == 403 and b"awaiting administrator approval" in blocked.data

    # 4. admin approves
    assert b"Account approved" in act(admin_client, user, "approve").data
    user = staff_row("sam@example.com")
    assert (user.account_status, user.is_active, user.approved_by_id) == (S.ACTIVE, True, admin.id)
    assert user.approved_at is not None and user.status_changed_by_id == admin.id

    # 5. the staff member can now sign in
    ok = app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD})
    assert ok.status_code == 302 and ok.headers["Location"].endswith("/dashboard/staff")
    for name in ("staff_created", "staff_verification_completed", "staff_approved"):
        assert events(name), name
    approved = events("staff_approved")[0]
    assert (approved.user_id, approved.target_user_id) == (admin.id, user.id)


def test_didit_approval_only_moves_accounts_that_are_waiting_for_verification(app, provider):
    waiting = make_staff("w@example.com", status=S.PENDING_VERIFICATION, verified=False)
    already = make_staff("a@example.com", status=S.ACTIVE, verified=False)
    boss = User(email="adm@example.com", role=Role.ADMIN, is_active=True)
    db.session.add(boss)
    db.session.commit()
    for user in (waiting, already, boss):
        v = IdentityVerification(user_id=user.id, provider="didit", provider_session_id=str(uuid.uuid4()),
                                 environment="sandbox", status="in_progress", purpose="kyc")
        db.session.add(v)
        db.session.commit()
        idv.apply_provider_status(v, "Approved", source="test")
        db.session.commit()
    db.session.expire_all()
    assert (waiting.account_status, already.account_status, boss.account_status) == (S.PENDING_APPROVAL, S.ACTIVE, S.ACTIVE)
    assert len(events("staff_verification_completed")) == 1


def test_a_failed_verification_never_reaches_approval(admin_client):
    user = make_staff(status=S.PENDING_VERIFICATION, verified=False)
    v = IdentityVerification(user_id=user.id, provider="didit", provider_session_id=str(uuid.uuid4()),
                             environment="sandbox", status="in_progress", purpose="kyc")
    db.session.add(v)
    db.session.commit()
    idv.apply_provider_status(v, "Declined", source="test")
    db.session.commit()
    assert staff_row("sam@example.com").account_status == S.PENDING_VERIFICATION
    assert b"Only accounts awaiting approval" in act(admin_client, user, "approve").data
    assert staff_row("sam@example.com").account_status == S.PENDING_VERIFICATION


# ----------------------------------------------------------------------------- approve / reject
def test_only_verified_accounts_awaiting_approval_can_be_approved(admin_client):
    unverified = make_staff("u@example.com", status=S.PENDING_APPROVAL, verified=False)
    assert b"verification is not complete" in act(admin_client, unverified, "approve").data
    assert staff_row("u@example.com").account_status == S.PENDING_APPROVAL
    active = make_staff("a@example.com")
    assert b"Only accounts awaiting approval" in act(admin_client, active, "approve").data
    ok = make_staff("ok@example.com", status=S.PENDING_APPROVAL)
    assert b"Account approved" in act(admin_client, ok, "approve").data


def test_rejecting_requires_a_reason_and_blocks_access(app, admin_client, admin):
    user = make_staff(status=S.PENDING_APPROVAL)
    token = user.staff_credential.enroll_token_hash
    assert b"Enter a reason" in act(admin_client, user, "reject", reason="").data
    assert b"Enter a reason" in act(admin_client, user, "reject", reason="no").data
    assert staff_row("sam@example.com").account_status == S.PENDING_APPROVAL
    assert b"Account rejected" in act(admin_client, user, "reject", reason="ID does not match").data
    user = staff_row("sam@example.com")
    assert (user.account_status, user.is_active, user.status_reason) == (S.REJECTED, False, "ID does not match")
    assert user.status_changed_by_id == admin.id and user.status_changed_at is not None
    assert user.staff_credential.enroll_token_hash is None and token != user.staff_credential.enroll_token_hash
    r = app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD})
    assert r.status_code == 401
    (event,) = events("staff_rejected")
    assert event.user_id == admin.id and "ID does not match" in event.detail


def test_active_staff_cannot_be_rejected(admin_client):
    user = make_staff()
    assert b"Only pending accounts" in act(admin_client, user, "reject", reason="because").data
    assert staff_row("sam@example.com").account_status == S.ACTIVE


# ----------------------------------------------------------------------------- suspend / reactivate / deactivate
def test_suspending_cuts_off_access_immediately_and_can_be_undone(app, admin_client, client_for):
    user = make_staff()
    staff_session = client_for(user)
    assert staff_session.get("/dashboard/staff").status_code == 200

    assert b"Enter a reason" in act(admin_client, user, "suspend", reason="").data
    assert staff_row("sam@example.com").account_status == S.ACTIVE
    assert b"Account suspended" in act(admin_client, user, "suspend", reason="Left the till open").data
    user = staff_row("sam@example.com")
    assert (user.account_status, user.is_active, user.status_reason) == (S.SUSPENDED, False, "Left the till open")

    assert staff_session.get("/dashboard/staff").status_code == 302         # the live session is revoked
    with staff_session.session_transaction() as sess:
        assert "_user_id" not in sess
    assert app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD}).status_code == 401

    assert b"Account reactivated" in act(admin_client, user, "reactivate").data
    user = staff_row("sam@example.com")
    assert (user.account_status, user.is_active) == (S.ACTIVE, True)
    assert app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD}).status_code == 302
    assert events("staff_suspended") and events("staff_reactivated")


def test_reactivation_cannot_bypass_identity_verification(admin_client):
    user = make_staff(status=S.SUSPENDED, verified=False, active=False)
    assert b"not identity-verified" in act(admin_client, user, "reactivate").data
    assert staff_row("sam@example.com").account_status == S.SUSPENDED
    pending = make_staff("p@example.com", status=S.PENDING_APPROVAL)
    assert b"Only suspended accounts" in act(admin_client, pending, "reactivate").data


def test_only_active_accounts_can_be_suspended(admin_client):
    for i, status in enumerate((S.PENDING_VERIFICATION, S.PENDING_APPROVAL, S.REJECTED, S.DEACTIVATED)):
        user = make_staff(f"x{i}@example.com", status=status, active=status in AccountStatus.PENDING)
        assert b"Only active accounts" in act(admin_client, user, "suspend", reason="reason here").data


def test_deactivation_keeps_the_record_and_removes_access(app, admin_client, client_for):
    user = make_staff()
    live = client_for(user)
    assert b"Enter a reason" in act(admin_client, user, "deactivate", reason="").data
    assert b"Account deactivated" in act(admin_client, user, "deactivate", reason="Resigned").data
    user = staff_row("sam@example.com")                                     # row is kept, never deleted
    assert (user.account_status, user.is_active, user.status_reason) == (S.DEACTIVATED, False, "Resigned")
    assert user.staff_credential.enroll_token_hash is None
    assert live.get("/dashboard/staff").status_code == 302
    assert app.test_client().post("/auth/login", data={"identifier": "sam@example.com", "password": STAFF_PASSWORD}).status_code == 401
    assert b"already deactivated" in act(admin_client, user, "deactivate", reason="again").data
    assert b"Only suspended" in act(admin_client, user, "reactivate").data
    assert events("staff_deactivated")


def test_any_non_deactivated_account_can_be_deactivated(admin_client):
    for i, status in enumerate((S.PENDING_VERIFICATION, S.PENDING_APPROVAL, S.ACTIVE, S.SUSPENDED, S.REJECTED)):
        user = make_staff(f"d{i}@example.com", status=status, active=status in (S.ACTIVE, *AccountStatus.PENDING))
        assert b"Account deactivated" in act(admin_client, user, "deactivate", reason="clean up").data
        assert staff_row(f"d{i}@example.com").account_status == S.DEACTIVATED


# ----------------------------------------------------------------------------- guards
def test_an_admin_cannot_act_on_themselves_or_on_other_admins(app, admin_client, admin, make_user):
    other = make_user("other@example.com", role=Role.ADMIN)
    for target in (admin, other):
        for action, data in (("suspend", {"reason": "nope nope"}), ("deactivate", {"reason": "nope nope"}),
                             ("reject", {"reason": "nope nope"}), ("approve", {}), ("reactivate", {}), ("enroll-link", {})):
            assert admin_client.post(f"/admin/staff/{target.id}/{action}", data=data).status_code == 404
        assert admin_client.get(f"/admin/staff/{target.id}").status_code == 404
    db.session.expire_all()
    assert (admin.account_status, other.account_status, other.role) == (S.ACTIVE, S.ACTIVE, Role.ADMIN)
    with pytest.raises(ActionError):
        services.suspend(admin.id, admin, "reason here")                    # the service refuses too


def test_no_role_can_be_changed_from_this_module(admin_client):
    user = make_staff(status=S.PENDING_APPROVAL)
    act(admin_client, user, "approve", role="admin")
    assert staff_row("sam@example.com").role == Role.STAFF
    mine = [r for r in admin_client.application.url_map.iter_rules() if r.endpoint.startswith("staff_admin.")]
    assert mine and not [r for r in mine if "role" in r.rule or "promote" in r.rule]


def test_only_an_active_administrator_may_use_the_service(make_user):
    user = make_staff()
    for actor in (make_user("s@example.com"), make_user("susp@example.com", role=Role.ADMIN, status=S.SUSPENDED, active=False)):
        with pytest.raises(ActionError):
            services.suspend(user.id, actor, "reason here")


# ----------------------------------------------------------------------------- listing
def test_filters_search_sort_and_cards(admin_client):
    make_staff("a@example.com", name="Ana Active")
    make_staff("p@example.com", status=S.PENDING_VERIFICATION, verified=False, name="Pia Pending")
    make_staff("w@example.com", status=S.PENDING_APPROVAL, name="Wes Waiting")
    make_staff("s@example.com", status=S.SUSPENDED, active=False, name="Sue Suspended")
    make_staff("r@example.com", status=S.REJECTED, active=False, name="Rae Rejected")
    make_staff("d@example.com", status=S.DEACTIVATED, active=False, name="Dan Deactivated")

    everyone = html(admin_client, "/admin/staff/")
    assert all(n in everyone for n in ("Ana Active", "Pia Pending", "Wes Waiting", "Sue Suspended", "Rae Rejected", "Dan Deactivated"))
    for status, only in (("active", "Ana Active"), ("pending_verification", "Pia Pending"), ("pending_approval", "Wes Waiting"),
                         ("suspended", "Sue Suspended"), ("rejected", "Rae Rejected"), ("deactivated", "Dan Deactivated")):
        page = html(admin_client, f"/admin/staff/?status={status}")
        assert only in page and sum(n in page for n in ("Ana Active", "Pia Pending", "Wes Waiting", "Sue Suspended", "Rae Rejected", "Dan Deactivated")) == 1
    assert "Pia Pending" in html(admin_client, "/admin/staff/?q=pia") and "Ana Active" not in html(admin_client, "/admin/staff/?q=pia")
    assert "w@example.com" in html(admin_client, "/admin/staff/?q=w%40example")
    assert "Ana Active" in html(admin_client, "/admin/staff/?sort=name") and html(admin_client, "/admin/staff/?sort=bogus")
    assert html(admin_client, "/admin/staff/?status=bogus") and admin_client.get("/admin/staff/?page=99").status_code == 200
    counts = services.status_counts()
    assert counts["total"] == 6 and counts[S.ACTIVE] == 1 and counts["suspended_deactivated"] == 2


def test_the_list_shows_identity_status_and_dates_without_sensitive_data(admin_client):
    make_staff()
    page = html(admin_client, "/admin/staff/")
    assert "Verified" in page and "Never" in page
    for hidden in ("password", "provider_session_id", "didit"):
        assert hidden not in page.lower()


def test_detail_page_lists_audit_activity(admin_client):
    user = make_staff()
    act(admin_client, user, "suspend", reason="Audit me please")
    page = html(admin_client, f"/admin/staff/{user.id}")
    assert "Staff suspended" in page and "Audit me please" in page and "boss@example.com" in page


# ----------------------------------------------------------------------------- CSRF
def test_csrf_protects_every_state_changing_staff_management_request():
    class CsrfOn(TestingConfig):
        WTF_CSRF_ENABLED = True
    app = _make_app(CsrfOn)
    with app.app_context():
        db.create_all()
        boss = User(email="boss@example.com", role=Role.ADMIN, is_active=True)
        db.session.add(boss)
        db.session.commit()
        c = app.test_client()
        _login(c, boss)
        for url in ("/admin/staff/new", "/admin/staff/1/approve", "/admin/staff/1/reject", "/admin/staff/1/suspend",
                    "/admin/staff/1/reactivate", "/admin/staff/1/deactivate", "/admin/staff/1/enroll-link"):
            assert c.post(url, data={"reason": "x y z"}).status_code == 400, url
        db.session.remove()
        db.drop_all()
