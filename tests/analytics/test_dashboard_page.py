"""The Analytics page: server-rendered figures, filters, navigation and CSP safety."""
import re
from pathlib import Path

import pytest

from app.analytics import services

RANGE = "range=custom&start=2026-11-01&end=2026-11-07"
EN_DASH = "\u2013"


def page(client, qs=RANGE):
    r = client.get(f"/admin/analytics/?{qs}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def kpi_block(html, key):
    """The HTML of one KPI card (from its data-kpi marker to the next card or the footnote)."""
    start = html.index(f'data-kpi="{key}"')
    ends = [i for i in (html.find("data-kpi=", start + 1), html.find("an-footnote", start)) if i != -1]
    return html[start:min(ends)]


# ---- header, filters ---------------------------------------------------------

def test_header_text(admin_client):
    html = page(admin_client)
    assert "Analytics &amp; Reports" in html
    assert "Business performance, operational trends, and predictive insights." in html


def test_quick_filters_and_active_state_default(admin_client):
    html = page(admin_client, "")
    for preset in ("today", "last_7", "last_30", "this_month", "last_month"):
        assert f"range={preset}" in html
    assert re.search(r'class="an-chip active" href="[^"]*range=last_30"', html)
    assert "Showing" in html and "Philippine time" in html


def test_custom_range_form_keeps_values_and_limits_dates(admin_client):
    html = page(admin_client)
    assert 'name="range" value="custom"' in html
    assert 'name="start" value="2026-11-01"' in html and 'name="end" value="2026-11-07"' in html
    assert 'min="2020-01-01"' in html and re.search(r'max="\d{4}-\d{2}-\d{2}"', html)


def test_period_and_comparison_labels(admin_client):
    html = page(admin_client)
    assert f"Nov 01, 2026 {EN_DASH} Nov 07, 2026" in html
    assert f"Oct 25, 2026 {EN_DASH} Oct 31, 2026" in html


def test_invalid_range_shows_message_and_falls_back(admin_client):
    html = page(admin_client, "range=custom&start=2026-13-01&end=2026-13-02")
    assert "real calendar date" in html
    assert re.search(r'class="an-chip active" href="[^"]*range=last_30"', html)


def test_refresh_link_keeps_the_selected_range(admin_client):
    html = page(admin_client)
    assert 'id="an-refresh"' in html
    assert "range=custom&amp;start=2026-11-01&amp;end=2026-11-07" in html


# ---- KPI cards show real database values -------------------------------------

def test_kpi_cards_show_database_values_and_comparisons(admin_client, dataset):
    html = page(admin_client)
    assert html.count("data-kpi=") == 6
    orders = kpi_block(html, "orders")
    assert ">4<" in orders.replace(" ", "").replace("\n", "") and "100.0%" in orders
    gross = kpi_block(html, "gross_order_value")
    assert "\u20b1980.00" in gross and "308.3%" in gross and "\u20b1240.00" in gross and "an-good" in gross
    paid = kpi_block(html, "payments_collected")
    assert "\u20b1250.00" in paid and "25.0%" in paid and "\u20b1200.00" in paid
    owed = kpi_block(html, "outstanding_balance")
    assert "\u20b1330.00" in owed and "\u20b140.00" in owed and "an-bad" in owed   # more owed is bad news
    aov = kpi_block(html, "average_order_value")
    assert "\u20b1245.00" in aov and "104.2%" in aov
    ret = kpi_block(html, "returning_customers")
    assert "+1" in ret and "No percentage is shown" in ret                       # previous period was zero


def test_gross_value_and_collections_are_explained_separately(admin_client, dataset):
    html = page(admin_client)
    assert "Gross order value" in html and "Payments collected" in html
    assert "never mixed" in html


def test_empty_period_renders_safely(admin_client, app):
    html = page(admin_client, "range=custom&start=2026-01-01&end=2026-01-07")
    assert "\u20b10.00" in kpi_block(html, "gross_order_value")
    aov = kpi_block(html, "average_order_value")
    assert "\u2014" in aov and "No comparison" in aov


# ---- present_kpis (pure formatting rules) ------------------------------------

def _card(key, value, previous, change, fmt="currency"):
    return {"key": key, "label": key, "format": fmt, "value": value, "previous": previous, "change": change, "definition": None}


def test_present_kpis_rules():
    up = {"direction": "up", "percent": "10.0", "absolute": "10", "current": "110", "previous": "100"}
    down = {**up, "direction": "down", "percent": "-10.0", "absolute": "-10"}
    flat = {**up, "direction": "flat", "percent": "0.0", "absolute": "0"}
    zero_base = {**up, "percent": None, "absolute": "40.00", "previous": "0.00"}
    cards = services.present_kpis([
        _card("gross_order_value", "110.00", "100.00", up),
        _card("outstanding_balance", "110.00", "100.00", up),      # increase of money owed = bad
        _card("outstanding_balance", "90.00", "100.00", down),     # decrease of money owed = good
        _card("orders", 5, 5, flat, "count"),
        _card("outstanding_balance", "40.00", "0.00", zero_base),
        _card("average_order_value", None, "10.00", None),
    ])
    assert [c["tone"] for c in cards] == ["good", "bad", "good", "neutral", "bad", "neutral"]
    assert cards[0]["delta_text"] == "10.0%" and cards[0]["arrow"] == "\u25b2" and cards[0]["value_display"] == "\u20b1110.00"
    assert cards[2]["arrow"] == "\u25bc" and cards[2]["delta_text"] == "10.0%"
    assert cards[3]["delta_text"] == "No change" and cards[3]["value_display"] == "5"
    assert cards[4]["delta_text"] == "+\u20b140.00" and cards[4]["hint"]
    assert cards[5]["value_display"] == "\u2014" and cards[5]["delta_text"] == "No comparison"


# ---- tabs, wiring, accessibility ---------------------------------------------

def test_tabs_and_panels_exist(admin_client):
    html = page(admin_client)
    for key in ("sales", "orders", "services", "customers", "payments", "balances"):
        assert f'data-tab="{key}"' in html
        assert f'id="panel-{key}"' in html and f'role="tabpanel"' in html
    assert 'role="tablist"' in html
    assert re.search(r'data-api-base="/admin/analytics/api/"', html)
    assert 'data-query="range=custom&amp;start=2026-11-01&amp;end=2026-11-07"' in html


def test_charts_have_text_alternatives(admin_client):
    html = page(admin_client)
    assert html.count("<canvas") == html.count('role="img"') >= 6
    assert html.count("View as data table") >= 6


def test_assets_are_served_to_admins(admin_client):
    js = admin_client.get("/admin/analytics/assets/js/analytics.js")
    css = admin_client.get("/admin/analytics/assets/css/analytics.css")
    assert js.status_code == 200 and css.status_code == 200
    assert b"innerHTML" not in js.data                       # data is only ever inserted as text


def test_page_references_local_scripts_only(admin_client):
    html = page(admin_client)
    srcs = re.findall(r'<script[^>]*\ssrc="([^"]+)"', html)
    assert any(s.endswith("js/analytics.js") for s in srcs) and any(s.endswith("vendor/chart.umd.js") for s in srcs)
    assert all(s.startswith("/") for s in srcs), srcs      # same-origin only, as the CSP requires


def test_page_has_no_inline_script_style_or_handlers(admin_client, dataset):
    html = page(admin_client)
    assert not re.search(r"<script(?![^>]*\ssrc=)", html), "inline <script>"
    assert "<style" not in html and not re.search(r"\sstyle=", html), "inline style"
    assert not re.search(r"\son[a-z]+=", html), "inline event handler"


def test_vendored_chartjs_when_present(app):
    path = Path(app.root_path) / "analytics" / "static" / "vendor" / "chart.umd.js"
    if not path.exists():
        pytest.skip("Chart.js is not vendored yet (see app/analytics/static/vendor/README.md)")
    assert "Chart.js v4" in path.read_text(encoding="utf-8")[:400]


# ---- navigation + privacy ----------------------------------------------------

def test_sidebar_link_for_admin_only(admin_client, staff_client):
    admin_html = admin_client.get("/dashboard/admin").get_data(as_text=True)
    assert 'href="/admin/analytics/"' in admin_html
    staff_html = staff_client.get("/dashboard/staff").get_data(as_text=True)
    assert "/admin/analytics" not in staff_html


def test_sidebar_link_is_active_on_the_analytics_page(admin_client):
    html = page(admin_client)
    assert re.search(
        r'<a\s+class="lx-nav__link is-active"\s+href="/admin/analytics/"',
        html,
    )

def test_no_contact_numbers_in_analytics_output(admin_client, dataset):
    assert "TESTCONTACT" not in page(admin_client)
    for section in ("customers", "orders", "services", "payments"):
        body = admin_client.get(f"/admin/analytics/api/{section}?{RANGE}").get_data(as_text=True)
        assert "TESTCONTACT" not in body, section
