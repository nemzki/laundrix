"""Database aggregations checked against the hand-computed `dataset` fixture
(see conftest.py for the full table).  Range P = Nov 1-7 2026; previous = Oct 25-31."""
from datetime import date
from decimal import Decimal as D

from app.analytics import calculations as calc
from app.analytics import queries, services
from app.analytics.periods import resolve_range
from app.payments import services as payment_services

from tests.analytics import factories as f

TODAY = date(2026, 11, 8)


def P():
    return resolve_range("custom", "2026-11-01", "2026-11-07", today=TODAY)


def PREV():
    return P().previous()


# ---- gross order value / orders ---------------------------------------------

def test_order_summary_current_period(dataset):
    # In P: O2 300 + O3 100 + O4 80 + O5 500 = 980 (4 orders). O7 (Nov 8 00:00 PHT) is excluded.
    s = queries.order_summary(P().start_utc, P().end_utc)
    assert (s["count"], s["gross"]) == (4, D("980.00"))
    assert s["awaiting_receipt"] == 1  # O4 receipt not confirmed


def test_order_summary_previous_period_includes_last_second(dataset):
    # O1 200 + O6 40 (Oct 31 23:59:59 PHT) = 240
    s = queries.order_summary(PREV().start_utc, PREV().end_utc)
    assert (s["count"], s["gross"]) == (2, D("240.00"))


def test_multi_item_order_is_not_multiplied_by_joins(dataset):
    # O2 has 3 items and 2 payments; its 300 must be counted exactly once.
    s = queries.order_summary(P().start_utc, P().end_utc)
    assert s["gross"] == D("980.00")
    wash = next(r for r in queries.service_breakdown(P().start_utc, P().end_utc) if r["name"] == "Wash")
    assert wash["orders"] == 3


def test_orders_by_status(dataset):
    got = queries.orders_by_status(P().start_utc, P().end_utc)
    assert got == {"processing": 1, "ready_for_pickup": 1, "order_received": 1, "completed": 1}


def test_orders_by_day_uses_philippine_dates(dataset):
    days = queries.orders_by_day(P().start_utc, P().end_utc)
    assert days[date(2026, 11, 2)] == {"orders": 2, "gross_order_value": D("400.00")}
    # O4 was created at Nov 2 16:00 UTC, which is Nov 3 00:00 in the Philippines.
    assert days[date(2026, 11, 3)] == {"orders": 1, "gross_order_value": D("80.00")}
    assert days[date(2026, 11, 4)] == {"orders": 1, "gross_order_value": D("500.00")}
    assert set(days) == {date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)}


# ---- payment ledger ---------------------------------------------------------

def test_collections_current_period(dataset):
    # payments: O2 100 + 50, O3 100 = 250.  O3's reversal was recorded Nov 8 => not in P.
    s = queries.ledger_summary(P().start_utc, P().end_utc)
    assert (s["payments"], s["reversals"], s["net"]) == (D("250.00"), D("0.00"), D("250.00"))
    assert (s["payment_count"], s["reversal_count"]) == (3, 0)


def test_reversal_lands_in_the_period_it_was_recorded(dataset):
    rng = resolve_range("custom", "2026-11-08", "2026-11-08", today=TODAY)
    s = queries.ledger_summary(rng.start_utc, rng.end_utc)
    assert (s["payments"], s["reversals"], s["net"]) == (D("0.00"), D("100.00"), D("-100.00"))
    assert s["reversal_count"] == 1
    # ...and the earlier period's collections were NOT rewritten:
    assert queries.ledger_summary(P().start_utc, P().end_utc)["net"] == D("250.00")


def test_collections_previous_period(dataset):
    assert queries.ledger_summary(PREV().start_utc, PREV().end_utc)["net"] == D("200.00")


def test_collections_by_method(dataset):
    rows = {r["code"]: r for r in queries.ledger_by_method(P().start_utc, P().end_utc)}
    assert rows["cash"]["net"] == D("200.00") and rows["cash"]["payment_count"] == 2
    assert rows["gcash"]["net"] == D("50.00") and rows["gcash"]["label"] == "GCash"
    assert [r["code"] for r in queries.ledger_by_method(P().start_utc, P().end_utc)] == ["cash", "gcash"]


def test_payment_methods_are_read_dynamically(app, payment_methods):
    from app.extensions import db
    from app.models import PaymentMethod
    db.session.add(PaymentMethod(code="maya", label="Maya", requires_reference=False, sort_order=30, is_active=True))
    db.session.commit()
    c = f.make_customer("Eve", f.local(2026, 11, 2))
    o = f.make_order(c, 200, f.local(2026, 11, 2, 9))
    f.add_payment(o, 150, f.local(2026, 11, 2, 10), "cash")
    f.add_payment(o, 40, f.local(2026, 11, 2, 11), "maya")
    db.session.commit()
    rows = queries.ledger_by_method(P().start_utc, P().end_utc)
    assert {r["code"] for r in rows} == {"cash", "maya"}
    out = services.build_payments(P())
    maya = next(m for m in out["methods"] if m["code"] == "maya")
    assert maya["net"] == "40.00" and maya["share"] == "21.1"  # 40 / 190


def test_ledger_by_day(dataset):
    days = queries.ledger_by_day(P().start_utc, P().end_utc)
    assert days[date(2026, 11, 2)]["payments"] == D("200.00")
    assert days[date(2026, 11, 3)]["payments"] == D("50.00")


# ---- outstanding balances ---------------------------------------------------

def test_outstanding_all_time(dataset):
    o = queries.outstanding()
    assert (o["unpaid_orders"], o["unpaid_amount"]) == (4, D("280.00"))   # O3 100, O4 80, O6 40, O7 60
    assert (o["partial_orders"], o["partial_amount"]) == (1, D("150.00"))  # O2
    assert o["balance_total"] == D("430.00")
    assert o["customers_owing"] == 3                                       # Ana, Ben, Cara
    assert (o["untracked_orders"], o["untracked_order_value"]) == (1, D("500.00"))  # O5 is legacy


def test_outstanding_matches_existing_payments_service(dataset):
    count, total = payment_services.outstanding_summary()
    o = queries.outstanding()
    assert count == o["unpaid_orders"] + o["partial_orders"]
    assert total == o["balance_total"]


def test_outstanding_scoped_to_orders_created_in_period(dataset):
    o = queries.outstanding(P().start_utc, P().end_utc)
    assert o["balance_total"] == D("330.00")      # O2 150 + O3 100 + O4 80
    assert (o["unpaid_orders"], o["partial_orders"]) == (2, 1)
    assert queries.outstanding(PREV().start_utc, PREV().end_utc)["balance_total"] == D("40.00")  # O6


def test_reversed_payment_is_not_double_counted(dataset):
    # O3: +100 payment, -100 reversal => net 0 => the full 100 is owed (not 200, not 0).
    o = queries.outstanding(f.local(2026, 11, 2, 23), f.local(2026, 11, 3))
    assert o["balance_total"] == D("100.00")


def test_overpayment_never_creates_negative_balance(app, payment_methods):
    from app.extensions import db
    c = f.make_customer("Over", f.local(2026, 11, 2))
    o = f.make_order(c, 100, f.local(2026, 11, 2, 9))
    f.add_payment(o, 150, f.local(2026, 11, 2, 10))
    db.session.commit()
    res = queries.outstanding()
    assert res["balance_total"] == D("0.00") and res["customers_owing"] == 0


# ---- services ---------------------------------------------------------------

def test_service_breakdown_separates_types_and_counts_snapshots(dataset):
    rows = {(r["item_type"], r["name"]): r for r in queries.service_breakdown(P().start_utc, P().end_utc)}
    wash = rows[("service", "Wash")]
    assert (calc.money(wash["quantity"]), wash["orders"], wash["item_revenue"]) == (D("4.00"), 3, D("320.00"))
    wdf = rows[("package", "Wash, Dry & Fold")]
    assert (calc.money(wdf["quantity"]), wdf["orders"], wdf["item_revenue"]) == (D("3.00"), 2, D("600.00"))
    fab = rows[("addon", "Fabcon")]
    assert (fab["orders"], fab["item_revenue"]) == (2, D("60.00"))


def test_service_report_excludes_addons_from_primary_ranking(dataset):
    out = services.build_services(P())
    assert [r["name"] for r in out["services"]] == ["Wash", "Wash, Dry & Fold"]
    assert [r["rank"] for r in out["services"]] == [1, 2]
    assert [r["name"] for r in out["addons"]] == ["Fabcon"]
    assert out["services"][0]["item_revenue"] == "320.00"
    assert "item revenue" in out["notes"]["revenue"].lower()


# ---- customers --------------------------------------------------------------

def test_customer_counts(dataset):
    c = queries.customer_counts(P().start_utc, P().end_utc)
    assert c == {"registered": 4, "new_registered": 3, "with_orders": 4,
                 "repeat": 1,   # only Ana has 2+ orders (O1, O6, O2); Ben's O7 is after the period
                 "active": 4, "returning": 1,  # Ana's first-ever order (Oct 28) predates Nov 1
                 "new_active": 3}


def test_customer_counts_previous_period(dataset):
    c = queries.customer_counts(PREV().start_utc, PREV().end_utc)
    assert (c["active"], c["returning"], c["new_active"]) == (1, 0, 1)


def test_repeat_rate_and_top_customers(dataset):
    out = services.build_customers(P())
    assert out["repeat_rate"] == "25.0"
    assert [c["name"] for c in out["top_customers"]] == ["Dan Uy", "Ana Cruz", "Ben Reyes", "Cara Lim"]
    assert all("contact" not in k and "phone" not in k for c in out["top_customers"] for k in c)


# ---- overview / comparisons --------------------------------------------------

def test_overview_cards_and_comparisons(dataset):
    cards = {c["key"]: c for c in services.build_overview(P())["kpis"]}
    assert [c["label"] for c in services.build_overview(P())["kpis"]] == [
        "Total Orders", "Gross Order Value", "Payments Collected",
        "Outstanding Balances", "Average Order Value", "Returning Customers"]
    assert cards["orders"]["value"] == 4 and cards["orders"]["change"]["percent"] == "100.0"
    g = cards["gross_order_value"]
    assert (g["value"], g["previous"], g["change"]["percent"]) == ("980.00", "240.00", "308.3")
    c = cards["payments_collected"]
    assert (c["value"], c["previous"], c["change"]["absolute"], c["change"]["percent"]) == ("250.00", "200.00", "50.00", "25.0")
    o = cards["outstanding_balance"]
    assert (o["value"], o["previous"]) == ("330.00", "40.00")
    a = cards["average_order_value"]
    assert (a["value"], a["previous"], a["change"]["percent"]) == ("245.00", "120.00", "104.2")
    r = cards["returning_customers"]
    assert (r["value"], r["previous"]) == (1, 0)
    assert r["change"]["percent"] is None and r["change"]["direction"] == "up"  # previous is zero


def test_gross_value_and_collections_are_kept_distinct(dataset):
    cards = {c["key"]: c for c in services.build_overview(P())["kpis"]}
    assert cards["gross_order_value"]["value"] != cards["payments_collected"]["value"]


def test_overview_on_empty_range_is_safe(app, payment_methods):
    rng = resolve_range("custom", "2026-01-01", "2026-01-07", today=TODAY)
    cards = {c["key"]: c for c in services.build_overview(rng)["kpis"]}
    assert cards["orders"]["value"] == 0 and cards["orders"]["change"]["percent"] is None
    assert cards["gross_order_value"]["value"] == "0.00"
    assert cards["average_order_value"]["value"] is None and cards["average_order_value"]["change"] is None


# ---- sales / orders sections --------------------------------------------------

def test_sales_series_weekly(dataset):
    out = services.build_sales(P(), "week")
    wk1, wk2 = out["points"]
    assert wk1["partial"] and wk1["orders"] == 0                      # Sun Nov 1 only
    assert wk2["orders"] == 4 and wk2["gross_order_value"] == D("980.00")
    assert wk2["net_collections"] == D("250.00")
    assert out["comparison"]["gross_order_value"]["percent"] == "308.3"


def test_sales_series_daily_covers_every_day_including_zero_days(dataset):
    out = services.build_sales(P(), "day")
    assert len(out["points"]) == 7
    assert [p["orders"] for p in out["points"]] == [0, 2, 1, 1, 0, 0, 0]


def test_order_sections_use_real_status_constants(dataset):
    out = services.build_orders(P(), "day")
    assert [s["status"] for s in out["by_status"]] == [
        "order_received", "pending_processing", "processing", "ready_for_pickup", "picked_up", "completed"]
    groups = {g["key"]: g["count"] for g in out["groups"]}
    assert groups == {"pending": 1, "processing": 1, "ready": 1, "completed": 1}
    assert out["total"] == 4 and out["awaiting_receipt"] == 1


def test_balances_section_separates_legacy_orders(dataset):
    out = services.build_balances()
    assert out["balance_total"] == "430.00"
    assert out["untracked_orders"] == 1 and out["untracked_order_value"] == "500.00"


def test_api_returns_the_same_numbers_as_the_services(admin_client, dataset):
    r = admin_client.get("/admin/analytics/api/overview?range=custom&start=2026-11-01&end=2026-11-07")
    # (today in the test run is real "now"; the range is in the past so it is valid)
    assert r.status_code == 200
    cards = {c["key"]: c for c in r.get_json()["kpis"]}
    assert cards["gross_order_value"]["value"] == "980.00"
