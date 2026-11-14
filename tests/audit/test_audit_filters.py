"""Server-side filtering, shop-local time handling, pagination and the empty state."""
from datetime import datetime

from tests.audit.conftest import add_row

URL = "/settings"


def page(client, query=""):
    r = client.get(URL + query)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def utc(y, m, d, h=0, mi=0, s=0):
    return datetime(y, m, d, h, mi, s)


def test_search_by_name_is_case_insensitive_and_treats_wildcards_literally(admin_client):
    add_row(name="Sam Cruz", description="by sam")
    add_row(name="Ana Reyes", description="by ana")
    html = page(admin_client, "?q=sAm")
    assert "by sam" in html and "by ana" not in html
    assert "by sam" not in page(admin_client, "?q=%25")       # a literal % matches nothing


def test_filter_by_action_module_and_result(admin_client):
    add_row(action="payment", module="payments", description="PAY-ROW")
    add_row(action="delete", module="customers", description="DEL-ROW")
    add_row(action="login_failed", module="auth", description="FAIL-ROW", success=False)
    assert "PAY-ROW" in page(admin_client, "?action=payment") and "DEL-ROW" not in page(admin_client, "?action=payment")
    html = page(admin_client, "?module=customers")
    assert "DEL-ROW" in html and "PAY-ROW" not in html
    html = page(admin_client, "?status=failed")
    assert "FAIL-ROW" in html and "PAY-ROW" not in html
    html = page(admin_client, "?status=success")
    assert "PAY-ROW" in html and "FAIL-ROW" not in html


def test_day_filter_uses_philippine_time(admin_client):
    # 2026-03-10 20:00 UTC is 04:00 on 11 March in Manila (UTC+8).
    add_row(when=utc(2026, 3, 10, 20, 0), description="LATE-UTC")
    add_row(when=utc(2026, 3, 10, 10, 0), description="MIDDAY")
    html = page(admin_client, "?day=2026-03-11")
    assert "LATE-UTC" in html and "MIDDAY" not in html
    assert "MIDDAY" in page(admin_client, "?day=2026-03-10")


def test_exact_date_time_range(admin_client):
    add_row(when=utc(2026, 3, 10, 1, 0), description="AT-0900")     # 09:00 Manila
    add_row(when=utc(2026, 3, 10, 5, 30), description="AT-1330")     # 13:30 Manila
    add_row(when=utc(2026, 3, 10, 9, 0), description="AT-1700")      # 17:00 Manila
    html = page(admin_client, "?start=2026-03-10T10:00&end=2026-03-10T14:00")
    assert "AT-1330" in html and "AT-0900" not in html and "AT-1700" not in html
    # the end minute is inclusive
    assert "AT-1330" in page(admin_client, "?start=2026-03-10T13:30&end=2026-03-10T13:30")


def test_date_only_range_covers_whole_days(admin_client):
    add_row(when=utc(2026, 3, 9, 20, 0), description="MAR10-0400")    # 10 Mar 04:00 Manila
    add_row(when=utc(2026, 3, 12, 15, 0), description="MAR12-2300")   # 12 Mar 23:00 Manila
    add_row(when=utc(2026, 3, 13, 1, 0), description="MAR13-0900")
    html = page(admin_client, "?start=2026-03-10&end=2026-03-12")
    assert "MAR10-0400" in html and "MAR12-2300" in html and "MAR13-0900" not in html


def test_invalid_filters_are_ignored_with_a_notice_not_an_error(admin_client):
    add_row(description="STILL-HERE")
    for q in ("?action=drop%20table", "?module=zzz", "?day=31-02-2026", "?start=garbage",
              "?status=maybe", "?page=abc", "?page=-4", "?q=" + "x" * 500):
        r = admin_client.get(URL + q)
        assert r.status_code == 200, q
    html = page(admin_client, "?action=bogus")
    assert "STILL-HERE" in html and "not recognised" in html


def test_reversed_range_is_ignored_with_a_notice(admin_client):
    add_row(description="ROW")
    html = page(admin_client, "?start=2026-03-12T10:00&end=2026-03-10T10:00")
    assert "ROW" in html and "date range is empty" in html


def test_newest_first_and_server_side_pagination(admin_client):
    for i in range(30):
        add_row(minutes_ago=100 - i, description=f"ENTRY-{i:02d}")
    first = page(admin_client)
    assert "ENTRY-29" in first and "ENTRY-20" in first and "ENTRY-19" not in first     # 10 per page
    assert first.index("ENTRY-29") < first.index("ENTRY-28")
    second = page(admin_client, "?page=2")
    assert "ENTRY-19" in second and "ENTRY-29" not in second
    assert "1&ndash;10 of 30" in first or "1–10 of 30" in first


def test_pagination_links_keep_the_active_filters(admin_client):
    for i in range(30):
        add_row(name="Sam Cruz", minutes_ago=i)
    html = page(admin_client, "?q=Sam")
    assert "q=Sam" in html and "page=2" in html            # the Next link carries the filter


def test_empty_state(admin_client):
    assert "No audit records found" in page(admin_client)
    add_row()
    assert "No audit records found" in page(admin_client, "?q=nobody")
    assert "Clear filters" in page(admin_client, "?q=nobody")


def test_long_text_and_markup_are_escaped(admin_client):
    add_row(description="<script>alert(1)</script>" + "y" * 400, name="<b>Evil</b>")
    html = page(admin_client)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html and "<b>Evil</b>" not in html
