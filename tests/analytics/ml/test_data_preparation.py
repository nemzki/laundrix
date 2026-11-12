"""Series building: complete days/weeks only, zero-filled, timezone-correct, gap-aware.  Pure tests.

Reference moment used throughout: NOW = 2026-11-11 04:00 UTC = Wednesday 12:00 in Manila, so
    as_of (shop-local "today")  = Wed 2026-11-11   (incomplete, never used)
    last usable full day        = Tue 2026-11-10
    last complete Mon-Sun week  = ends Sun 2026-11-08
"""
from dataclasses import fields
from datetime import date, datetime, timedelta

from app.analytics.ml import data_preparation as dp
from app.analytics.ml.policy import DEFAULT_POLICY
from app.analytics.ml.schemas import Series, Target

NOW = datetime(2026, 11, 11, 4, 0)
POLICY = DEFAULT_POLICY


def d(month, day):
    return date(2026, month, day)


def span(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def raw(**kw):
    return dp.RawData(**kw)


def dense_orders(start, end, n=1, gross=100.0):
    return {day: (n, gross) for day in span(start, end)}


# ---- empty / today / zero fill ---------------------------------------------------

def test_empty_database_gives_empty_series_not_errors():
    p = dp.assemble(raw(), NOW)
    for s in (p.orders_daily, p.orders_weekly, p.gross_daily, p.gross_weekly, p.collections_daily, p.collections_weekly):
        assert s.n == 0 and s.events == 0 and s.end is None and s.dates() == []
    assert p.services == () and p.issues == () and p.ledger_start is None
    assert p.as_of == d(11, 11)


def test_today_is_never_included_because_it_is_incomplete():
    p = dp.assemble(raw(orders_by_day={d(11, 9): (2, 200.0), d(11, 10): (1, 50.0), d(11, 11): (9, 900.0)}), NOW)
    assert p.orders_daily.end == d(11, 10)
    assert p.orders_daily.values == (2.0, 1.0) and p.orders_daily.events == 3
    assert p.gross_daily.values == (200.0, 50.0)


def test_days_without_orders_are_zero_filled_real_observations():
    p = dp.assemble(raw(orders_by_day={d(11, 1): (1, 10.0), d(11, 5): (2, 20.0), d(11, 10): (1, 5.0)}), NOW)
    s = p.orders_daily
    assert s.start == d(11, 1) and s.n == 10                          # Nov 1 .. Nov 10 inclusive
    assert s.values == (1, 0, 0, 0, 2, 0, 0, 0, 0, 1) and s.events == 4


def test_series_starts_at_the_first_eligible_order_never_earlier():
    p = dp.assemble(raw(orders_by_day={d(11, 6): (1, 10.0), d(11, 10): (1, 10.0)}), NOW)
    assert p.orders_daily.start == d(11, 6)


def test_timezone_decides_which_day_is_today():
    # 2026-11-10 15:59 UTC is still Nov 10 in Manila; 16:00 UTC is already Nov 11 there.
    assert dp.local_today(datetime(2026, 11, 10, 15, 59, 59)) == d(11, 10)
    assert dp.local_today(datetime(2026, 11, 10, 16, 0, 0)) == d(11, 11)
    early = dp.assemble(raw(orders_by_day={d(11, 8): (1, 1.0), d(11, 9): (1, 1.0)}), datetime(2026, 11, 10, 15, 59))
    late = dp.assemble(raw(orders_by_day={d(11, 8): (1, 1.0), d(11, 9): (1, 1.0)}), datetime(2026, 11, 10, 16, 1))
    assert early.orders_daily.end == d(11, 9) and late.orders_daily.end == d(11, 10)


def test_first_day_after_as_of_yields_nothing():
    p = dp.assemble(raw(orders_by_day={d(11, 11): (3, 30.0)}), NOW)          # only today's partial data
    assert p.orders_daily.n == 0


# ---- weekly ------------------------------------------------------------------------

def test_weekly_uses_complete_monday_sunday_weeks_only():
    p = dp.assemble(raw(orders_by_day=dense_orders(d(10, 26), d(11, 8), n=1, gross=100.0)), NOW)
    w = p.orders_weekly
    assert w.start == d(10, 26) and w.values == (7.0, 7.0) and w.events == 14      # Nov 9-10 is a partial week: dropped
    assert p.gross_weekly.values == (700.0, 700.0)
    assert w.end == d(11, 2)                                                       # start of the last complete week


def test_partial_first_week_is_dropped():
    p = dp.assemble(raw(orders_by_day=dense_orders(d(10, 28), d(11, 8))), NOW)     # starts on a Wednesday
    assert p.orders_weekly.start == d(11, 2) and p.orders_weekly.n == 1


def test_no_complete_week_yet_means_empty_weekly_series():
    p = dp.assemble(raw(orders_by_day=dense_orders(d(11, 3), d(11, 10))), NOW)
    assert p.orders_daily.n == 8 and p.orders_weekly.n == 0


def test_weekly_sum_equals_daily_sum_over_the_same_weeks():
    orders = {day: ((i % 4), 10.0 * (i % 4)) for i, day in enumerate(span(d(9, 7), d(11, 9)))}
    orders[d(9, 7)] = (1, 10.0)
    p = dp.assemble(raw(orders_by_day=orders), NOW)
    daily, weekly = p.orders_daily, p.orders_weekly
    covered = sum(daily.values[(weekly.start - daily.start).days:(weekly.start - daily.start).days + 7 * weekly.n])
    assert sum(weekly.values) == covered


# ---- gaps -------------------------------------------------------------------------------

def test_history_before_a_long_gap_is_excluded_and_reported():
    orders = {d(9, 1): (1, 10.0)}
    orders.update(dense_orders(d(10, 20), d(11, 10)))
    p = dp.assemble(raw(orders_by_day=orders), NOW)
    assert p.orders_daily.start == d(10, 20) and p.orders_daily.n == 22
    assert p.excluded_history[Target.ORDERS] == (d(10, 20) - d(9, 1)).days == 49
    assert "history_before_gap" in {i.code for i in p.issues}


def test_a_shorter_gap_is_kept_as_real_zero_days():
    orders = {d(10, 1): (1, 10.0)}
    orders.update(dense_orders(d(10, 15), d(11, 10)))                        # 13 zero days: below the 14-day threshold
    p = dp.assemble(raw(orders_by_day=orders), NOW)
    assert p.orders_daily.start == d(10, 1) and p.excluded_history[Target.ORDERS] == 0


def test_history_that_ends_inside_a_gap_has_no_recent_activity():
    p = dp.assemble(raw(orders_by_day={d(9, 1): (1, 10.0), d(10, 1): (1, 10.0)}), NOW)
    assert p.orders_daily.n == 0
    assert "no_recent_activity" in {i.code for i in p.issues}


# ---- collections ---------------------------------------------------------------------------

def test_collections_net_out_reversals_on_the_day_they_were_recorded():
    coll = {d(10, 25): (100.0, 0.0, 1, 0), d(10, 27): (0.0, 100.0, 0, 1), d(11, 9): (50.0, 0.0, 1, 0)}
    p = dp.assemble(raw(collections_by_day=coll, ledger_start=d(10, 20)), NOW)
    s = p.collections_daily
    assert s.start == d(10, 20) and s.n == 22                                    # Oct 20 .. Nov 10
    assert s.values[5] == 100.0 and s.values[7] == -100.0 and s.values[20] == 50.0
    assert s.events == 3 and s.unit == "PHP"


def test_collections_start_at_the_tracking_go_live_not_the_first_order():
    orders = dense_orders(d(9, 1), d(11, 10))                                    # orders exist long before tracking
    coll = {day: (10.0, 0.0, 1, 0) for day in span(d(10, 20), d(11, 10))}
    p = dp.assemble(raw(orders_by_day=orders, collections_by_day=coll, ledger_start=d(10, 20)), NOW)
    assert p.orders_daily.start == d(9, 1)
    assert p.collections_daily.start == d(10, 20) and p.ledger_start == d(10, 20)
    assert p.collections_daily.n < p.orders_daily.n                              # pre-tracking zeros are NOT invented


def test_collections_do_not_depend_on_orders():
    coll = {day: (10.0, 0.0, 1, 0) for day in span(d(10, 20), d(11, 10))}
    p = dp.assemble(raw(collections_by_day=coll, ledger_start=d(10, 20)), NOW)
    assert p.orders_daily.n == 0 and p.collections_daily.n == 22


def test_gross_value_and_collections_are_separate_series():
    orders = dense_orders(d(10, 20), d(11, 10), gross=500.0)
    coll = {day: (100.0, 0.0, 1, 0) for day in span(d(10, 20), d(11, 10))}
    p = dp.assemble(raw(orders_by_day=orders, collections_by_day=coll, ledger_start=d(10, 20)), NOW)
    assert p.gross_daily.values[0] == 500.0 and p.collections_daily.values[0] == 100.0
    assert p.gross_daily.target == Target.GROSS_VALUE and p.collections_daily.target == Target.COLLECTIONS
    assert p.series(Target.GROSS_VALUE, "day") is p.gross_daily and p.series(Target.COLLECTIONS, "week") is p.collections_weekly


# ---- service entities ----------------------------------------------------------------------------

def row(day, item_type, name, unit="load", orders=1, qty=2.0, sid=None, pid=None, aid=None, desc=None):
    return {"date": day, "item_type": item_type, "service_id": sid, "package_id": pid, "addon_id": aid,
            "name": name, "description": desc, "unit": unit, "orders": orders, "quantity": qty}


def test_entity_keys_prefer_ids_and_fall_back_to_snapshots():
    k = dp.entity_key
    assert k("service", 7, None, None, "Wash", None) == "service:7"
    assert k("package", None, 3, None, "Wash, Dry & Fold", "Clothes · 3KG-5KG") == "package:3"
    assert k("addon", None, None, 2, "Fabcon", None) == "addon:2"
    # catalog row deleted (FK became NULL): fall back to the snapshot, normalised
    assert k("service", None, None, None, "  Wash ", None) == k("service", None, None, None, "wash", None) == "service:~wash"
    assert k("package", None, None, None, "Wash, Dry & Fold", "Clothes · 3KG-5KG") == "package:~clothes · 3kg-5kg"
    assert k("service", 7, None, None, "Wash", None) != k("addon", None, None, 7, "Wash", None)     # types never collide


def test_established_service_gets_complete_weeks_and_quantities():
    rows = [row(day, "service", "Wash", sid=1) for day in span(d(10, 26), d(11, 8))]
    (e,) = dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)
    assert e.key == "service:1" and e.unit == "load" and e.total_orders == 14
    assert e.orders_weekly.start == d(10, 26) and e.orders_weekly.values == (7.0, 7.0)
    assert e.quantity_weekly.values == (14.0, 14.0) and e.quantity_weekly.unit == "load"


def test_new_service_has_no_history_until_its_first_complete_week():
    rows = [row(d(11, 4), "service", "Fresh", sid=9)]                       # introduced mid-week
    (e,) = dp.build_service_entities(rows, d(10, 1), d(11, 11), POLICY)
    assert e.total_orders == 1 and e.orders_weekly.n == 0                   # weeks before it existed are NOT zero demand


def test_history_before_the_shop_data_gap_is_excluded():
    rows = [row(day, "service", "Wash", sid=1) for day in span(d(10, 1), d(10, 10))]
    assert dp.build_service_entities(rows, d(10, 20), d(11, 11), POLICY) == []
    assert dp.build_service_entities(rows, None, d(11, 11), POLICY) == []
    assert dp.build_service_entities([], d(10, 20), d(11, 11), POLICY) == []


def test_deleted_catalog_references_are_merged_by_snapshot():
    rows = [row(d(10, 26), "service", "Wash ", sid=None), row(d(10, 27), "service", "wash", sid=None)]
    (e,) = dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)
    assert e.key == "service:~wash" and e.total_orders == 2


def test_renamed_service_stays_one_entity_and_uses_the_newest_label():
    rows = [row(d(10, 26), "service", "Wash", sid=1), row(d(11, 2), "service", "Wash & Rinse", sid=1)]
    (e,) = dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)
    assert e.label == "Wash & Rinse" and e.total_orders == 2


def test_packages_addons_and_services_stay_separate():
    rows = []
    for day in span(d(10, 26), d(11, 8)):
        rows += [row(day, "service", "Wash", sid=1, orders=3),
                 row(day, "package", "Wash, Dry & Fold", unit="package", pid=4, desc="Clothes · 3KG-5KG (small)", orders=2),
                 row(day, "package", "Wash, Dry & Fold", unit="package", pid=5, desc="Comforter · Queen", orders=1),
                 row(day, "addon", "Fabcon", unit="pc", aid=2, orders=1)]
    ents = {e.key: e for e in dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)}
    assert set(ents) == {"service:1", "package:4", "package:5", "addon:2"}
    assert ents["package:4"].label == "Clothes · 3KG-5KG (small)" and ents["package:5"].label == "Comforter · Queen"
    assert ents["addon:2"].item_type == "addon" and ents["service:1"].item_type == "service"
    ranked = [e.key for e in dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)]
    assert ranked[0] == "service:1"                                         # most orders first


def test_mixed_units_are_flagged_and_quantity_uses_the_dominant_unit():
    rows = [row(day, "service", "Wash", unit="load", orders=5, qty=5.0, sid=1) for day in span(d(10, 26), d(11, 1))]
    rows.append(row(d(11, 2), "service", "Wash", unit="kg", orders=1, qty=40.0, sid=1))
    rows += [row(day, "service", "Wash", unit="load", orders=5, qty=5.0, sid=1) for day in span(d(11, 3), d(11, 8))]
    (e,) = dp.build_service_entities(rows, d(10, 26), d(11, 11), POLICY)
    assert e.unit == "load" and [i.code for i in e.issues] == ["mixed_units"]
    assert sum(e.quantity_weekly.values) == 5.0 * 13                          # the 40 kg row is not mixed into loads
    assert sum(e.orders_weekly.values) == 5 * 13 + 1                          # but the order itself still counts as demand


def test_service_entities_flow_through_assemble():
    orders = dense_orders(d(10, 26), d(11, 8))
    rows = [row(day, "service", "Wash", sid=1) for day in span(d(10, 26), d(11, 8))]
    p = dp.assemble(raw(orders_by_day=orders, service_rows=rows), NOW)
    assert len(p.services) == 1 and p.services[0].orders_weekly.n == 2


# ---- privacy -----------------------------------------------------------------------------------------

def test_prepared_data_carries_no_personal_fields():
    banned = ("customer", "phone", "contact", "email", "password", "token", "address")
    for cls in (dp.PreparedData, dp.ServiceEntity, Series):
        for f in fields(cls):
            assert not any(b in f.name.lower() for b in banned), f"{cls.__name__}.{f.name}"
