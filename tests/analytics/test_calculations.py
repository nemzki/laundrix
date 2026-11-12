"""Pure maths.  No database."""
from datetime import date
from decimal import Decimal as D

from app.analytics import calculations as calc


def test_compare_increase_decrease_flat():
    c = calc.compare(D("150.00"), D("100.00"))
    assert (c.absolute, c.percent, c.direction) == (D("50.00"), D("50.0"), "up")
    c = calc.compare(D("75"), D("100"))
    assert (c.absolute, c.percent, c.direction) == (D("-25"), D("-25.0"), "down")
    c = calc.compare(5, 5)
    assert (c.absolute, c.percent, c.direction) == (0, D("0.0"), "flat")


def test_compare_zero_previous_never_divides_by_zero():
    c = calc.compare(10, 0)
    assert c.percent is None and c.direction == "up" and c.absolute == 10
    c = calc.compare(0, 0)
    assert c.percent is None and c.direction == "flat"


def test_compare_negative_previous_has_no_percentage():
    c = calc.compare(D("50"), D("-100"))  # net collections can go negative
    assert c.percent is None and c.direction == "up"


def test_compare_rounding_is_half_up_to_one_decimal():
    assert calc.compare(980, 240).percent == D("308.3")
    assert calc.compare(D("245.00"), D("120.00")).percent == D("104.2")


def test_change_as_dict_is_plain_strings():
    d = calc.compare(D("245.00"), D("120.00")).as_dict()
    assert d == {"current": "245.00", "previous": "120.00", "absolute": "125.00",
                 "percent": "104.2", "direction": "up"}
    assert calc.compare(1, 0).as_dict()["percent"] is None


def test_average_order_value():
    assert calc.average_order_value(D("980.00"), 4) == D("245.00")
    assert calc.average_order_value(D("100.00"), 3) == D("33.33")
    assert calc.average_order_value(D("0.00"), 0) is None


def test_balance_due_never_negative():
    assert calc.balance_due(300, 150) == D("150.00")
    assert calc.balance_due(100, 100) == D("0.00")
    assert calc.balance_due(100, 150) == D("0.00")  # overpayment


def test_share_percent():
    assert calc.share_percent(200, 250) == D("80.0")
    assert calc.share_percent(0, 250) == D("0.0")
    assert calc.share_percent(5, 0) is None
    assert calc.share_percent(5, D("-10")) is None


def test_money_rounds_half_up_and_handles_none_and_floats():
    assert calc.money(None) == D("0.00")
    assert calc.money(0.1 + 0.2) == D("0.30")
    assert calc.money("2.005") == D("2.01")


ZEROS = {"orders": 0, "gross": D("0.00")}


def test_daily_buckets_include_zero_days():
    daily = {date(2026, 11, 2): {"orders": 2, "gross": D("400.00")}}
    pts = calc.bucket_series(daily, date(2026, 11, 1), date(2026, 11, 3), "day", ZEROS)
    assert [p["orders"] for p in pts] == [0, 2, 0]
    assert [p["start"] for p in pts] == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert not any(p["partial"] for p in pts)


def test_weekly_buckets_are_monday_to_sunday_and_flag_partial_edges():
    # Nov 1 2026 is a Sunday: it belongs to the week that began Mon Oct 26.
    daily = {date(2026, 11, 2): {"orders": 2, "gross": D("400.00")},
             date(2026, 11, 3): {"orders": 1, "gross": D("80.00")}}
    pts = calc.bucket_series(daily, date(2026, 11, 1), date(2026, 11, 7), "week", ZEROS)
    assert [p["key"] for p in pts] == ["2026-10-26", "2026-11-02"]
    assert pts[0]["start"] == "2026-11-01" and pts[0]["end"] == "2026-11-01" and pts[0]["partial"]
    assert pts[1]["orders"] == 3 and pts[1]["gross"] == D("480.00")
    assert pts[1]["end"] == "2026-11-07" and pts[1]["partial"]  # week would run to Nov 8


def test_full_week_is_not_partial():
    pts = calc.bucket_series({}, date(2026, 11, 2), date(2026, 11, 8), "week", ZEROS)
    assert len(pts) == 1 and pts[0]["partial"] is False


def test_monthly_buckets():
    daily = {date(2026, 10, 31): {"orders": 1, "gross": D("40.00")},
             date(2026, 11, 1): {"orders": 2, "gross": D("10.00")}}
    pts = calc.bucket_series(daily, date(2026, 10, 1), date(2026, 11, 30), "month", ZEROS)
    assert [(p["label"], p["orders"], p["partial"]) for p in pts] == [("Oct 2026", 1, False), ("Nov 2026", 2, False)]


def test_bucket_sums_match_daily_sums():
    daily = {date(2026, 11, d): {"orders": d, "gross": D(d)} for d in range(1, 8)}
    for g in ("day", "week", "month"):
        pts = calc.bucket_series(daily, date(2026, 11, 1), date(2026, 11, 7), g, ZEROS)
        assert sum(p["orders"] for p in pts) == 28
        assert sum(p["gross"] for p in pts) == D(28)


def test_rank_items_orders_then_quantity_then_name():
    rows = [
        {"name": "Fold", "orders": 2, "quantity": D("5")},
        {"name": "Wash", "orders": 3, "quantity": D("4")},
        {"name": "Dry", "orders": 2, "quantity": D("9")},
        {"name": "Spin", "orders": 2, "quantity": D("5")},
    ]
    ranked = calc.rank_items(rows)
    assert [(r["rank"], r["name"]) for r in ranked] == [(1, "Wash"), (2, "Dry"), (3, "Fold"), (4, "Spin")]


def test_format_peso():
    assert calc.format_peso(D("1234.5")) == "\u20b11,234.50"
    assert calc.format_peso(980) == "\u20b1980.00"
    assert calc.format_peso(D("-100")) == "-\u20b1100.00"
    assert calc.format_peso(D("0.005")) == "\u20b10.01"
    assert calc.format_peso(None) == "\u2014"
