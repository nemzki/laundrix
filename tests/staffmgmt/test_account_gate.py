"""The central gate protects direct URLs and API calls the same way as the pages."""
import pytest

from app.models import AccountStatus, Role

OPERATIONAL_URLS = ["/dashboard/", "/dashboard/staff", "/orders/", "/orders/new", "/payments/outstanding"]


def test_anonymous_users_are_untouched(app):
    c = app.test_client()
    for url in OPERATIONAL_URLS:
        assert c.get(url).status_code == 302
    assert c.get("/").status_code == 200


@pytest.mark.parametrize("role,url", [(Role.STAFF, "/dashboard/staff"), (Role.STAFF, "/orders/"), (Role.ADMIN, "/dashboard/admin")])
def test_active_users_keep_working(make_user, client_for, role, url):
    assert client_for(make_user("ok@example.com", role=role)).get(url).status_code == 200


@pytest.mark.parametrize("status", AccountStatus.PENDING)
def test_pending_staff_cannot_reach_operational_features(make_user, client_for, status):
    c = client_for(make_user("p@example.com", status=status))
    for url in OPERATIONAL_URLS + ["/admin/services/", "/orders/customers"]:
        r = c.get(url)
        assert r.status_code == 302 and r.headers["Location"].endswith("/identity/"), (url, r.status_code)


@pytest.mark.parametrize("status", AccountStatus.PENDING)
def test_pending_staff_can_only_do_verification_and_sign_out(make_user, client_for, status):
    c = client_for(make_user("p@example.com", status=status))
    assert c.get("/identity/").status_code == 200
    assert c.get("/core/static/css/base.css").status_code == 200
    assert c.get("/does-not-exist").status_code == 404           # unknown URLs are not hijacked
    assert c.get("/auth/login").status_code in (200, 302)
    out = c.post("/auth/logout")
    assert out.status_code == 302 and "/identity" not in out.headers["Location"]


@pytest.mark.parametrize("status", AccountStatus.PENDING)
def test_pending_staff_cannot_post_or_call_json_endpoints(make_user, client_for, status):
    c = client_for(make_user("p@example.com", status=status))
    assert c.post("/orders/new/quote", json={}).status_code == 403
    assert c.post("/orders/new/confirm", json={}).status_code == 403
    assert c.post("/orders/LX-X/payments", json={"entries": []}).status_code == 403
    assert c.get("/orders/customers/search?q=ab").status_code == 302


@pytest.mark.parametrize("status", [AccountStatus.SUSPENDED, AccountStatus.DEACTIVATED, AccountStatus.REJECTED])
def test_blocked_accounts_lose_their_session_immediately(make_user, client_for, status):
    c = client_for(make_user("b@example.com", status=status, active=False))
    r = c.get("/orders/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    with c.session_transaction() as sess:
        assert "_user_id" not in sess                                # session revoked
    assert c.get("/orders/").status_code == 302                      # and stays signed out
    assert c.post("/orders/new/quote", json={}).status_code == 302


def test_revoked_users_are_signed_out_but_public_pages_still_work(make_user, client_for):
    c = client_for(make_user("b@example.com", status=AccountStatus.SUSPENDED, active=False))
    r = c.get("/")
    assert r.status_code == 200                                       # public page, not a redirect loop
    # The base template renders (and thereby consumes) flash messages, so check the page itself:
    # the revoked user is told why they were signed out.
    assert "Your account is suspended." in r.get_data(as_text=True)
    with c.session_transaction() as sess:
        assert "_user_id" not in sess and "_fresh" not in sess


def test_suspending_a_signed_in_user_cuts_them_off_on_the_next_request(app, make_user, client_for):
    from app.extensions import db
    user = make_user("live@example.com")
    c = client_for(user)
    assert c.get("/orders/").status_code == 200
    user.account_status, user.is_active = AccountStatus.SUSPENDED, False
    db.session.commit()
    assert c.get("/orders/").status_code == 302
    assert c.get("/dashboard/").status_code == 302


def test_disabled_flag_alone_also_revokes(make_user, client_for):
    c = client_for(make_user("x@example.com", active=False))
    assert c.get("/orders/").status_code == 302


def test_active_staff_still_cannot_use_admin_functions(make_user, client_for):
    c = client_for(make_user("s@example.com"))
    assert c.get("/admin/services/").status_code == 403
    assert c.get("/payments/").status_code == 403
    assert c.get("/orders/customers").status_code == 403
