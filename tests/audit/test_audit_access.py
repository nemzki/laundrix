"""Only administrators see Audit Logs (a card in Personal Settings); nobody can write through the web."""
from app.extensions import db
from app.models import AuditLog
from tests.audit.conftest import add_row

SETTINGS = "/settings"
OLD_URL = "/admin/audit-logs/"


def test_admin_sees_the_card_inside_personal_settings_and_it_is_not_cached(admin_client):
    add_row(description="Hello audit")
    r = admin_client.get(SETTINGS)
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "Hello audit" in html and 'id="audit-logs"' in html
    assert "Account &amp; Security" in html and "no-store" in r.headers["Cache-Control"]


def test_staff_settings_page_never_contains_audit_data(staff_client):
    add_row(description="TOP-SECRET-ROW")
    for q in ("", "?q=sam&action=update&page=2"):
        r = staff_client.get(SETTINGS + q)
        html = r.get_data(as_text=True)
        assert r.status_code == 200
        assert "TOP-SECRET-ROW" not in html and 'id="audit-logs"' not in html and "Audit Logs" not in html


def test_old_url_is_admin_only_and_forwards_to_the_card(anon_client, staff_client, admin_client):
    r = anon_client.get(OLD_URL)
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]
    assert staff_client.get(OLD_URL + "?q=x").status_code == 403
    r = admin_client.get(OLD_URL + "?q=sam")
    assert r.status_code == 302 and "/settings?q=sam" in r.headers["Location"] and r.headers["Location"].endswith("#audit-logs")


def test_there_is_no_sidebar_link(admin_client):
    assert "/admin/audit-logs" not in admin_client.get("/orders/").get_data(as_text=True)


def test_there_is_no_way_to_write_or_delete_over_http(admin_client, staff_client):
    row = add_row()
    for client in (admin_client, staff_client):
        for method in ("post", "put", "patch", "delete"):
            r = getattr(client, method)(OLD_URL + str(row.id), json={"description": "x"})
            assert r.status_code in (403, 404, 405), (method, r.status_code)
        assert client.post(OLD_URL, json={}).status_code in (403, 405)
    db.session.expire_all()
    assert db.session.scalar(db.select(db.func.count(AuditLog.id))) == 1
    assert db.session.get(AuditLog, row.id).description == "Updated something"
