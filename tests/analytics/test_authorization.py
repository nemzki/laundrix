"""Every analytics route is administrator-only, enforced on the backend."""
import re


def _analytics_urls(app):
    urls = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("analytics."):
            url = re.sub(r"<(?:path:)?section>", "sales", rule.rule)
            url = re.sub(r"<(?:path:)?filename>", "x.css", url)
            urls.append((rule.endpoint, url))
    return urls


def test_blueprint_registered_with_expected_routes(app):
    endpoints = {e for e, _ in _analytics_urls(app)}
    assert {"analytics.index", "analytics.api_overview", "analytics.api_section", "analytics.static"} <= endpoints


def test_admin_can_open_dashboard(admin_client):
    r = admin_client.get("/admin/analytics/")
    assert r.status_code == 200
    assert b"Analytics" in r.data


def test_staff_gets_403_on_every_analytics_route(app, staff_client):
    for endpoint, url in _analytics_urls(app):
        assert staff_client.get(url).status_code == 403, f"{endpoint} ({url}) is not blocked for staff"


def test_anonymous_is_redirected_to_login_on_every_analytics_route(app, anon_client):
    for endpoint, url in _analytics_urls(app):
        r = anon_client.get(url)
        assert r.status_code == 302, f"{endpoint} ({url}) did not redirect"
        assert "login" in r.headers["Location"]


def test_staff_cannot_probe_unknown_sections(staff_client):
    assert staff_client.get("/admin/analytics/api/nonsense").status_code == 403


def test_admin_unknown_section_is_404(admin_client):
    assert admin_client.get("/admin/analytics/api/nonsense").status_code == 404


def test_admin_json_is_not_cacheable(admin_client):
    r = admin_client.get("/admin/analytics/api/overview?range=last_7")
    assert r.status_code == 200
    assert "no-store" in r.headers["Cache-Control"]


def test_bad_date_returns_400_json_not_500(admin_client):
    r = admin_client.get("/admin/analytics/api/overview?range=custom&start=2026-13-01&end=2026-13-02")
    assert r.status_code == 400
    assert "error" in r.get_json()
    r = admin_client.get("/admin/analytics/api/sales?range=last_7&granularity=hour")
    assert r.status_code == 400


def test_dashboard_page_survives_bad_dates(admin_client):
    r = admin_client.get("/admin/analytics/?range=custom&start=bad&end=bad")
    assert r.status_code == 200


def test_every_section_endpoint_answers_for_admin_on_empty_database(admin_client):
    for section in ("sales", "orders", "services", "customers", "payments", "balances"):
        r = admin_client.get(f"/admin/analytics/api/{section}?range=last_30")
        assert r.status_code == 200, section
