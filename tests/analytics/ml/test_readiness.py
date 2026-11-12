"""Readiness decisions, messages and the insufficient-data state.  Pure tests."""
import json
from datetime import date, datetime, timezone

from app.analytics.ml import data_preparation as dp
from app.analytics.ml import readiness as rd
from app.analytics.ml.policy import DEFAULT_POLICY, INSUFFICIENT_DATA_MESSAGE, Policy, WindowRule
from app.analytics.ml.schemas import ModelStatus, ReadinessStatus, Series, Target, Unit

START = date(2026, 1, 5)
NOW = datetime(2026, 11, 11, 4, 0)


def daily(n, events, target=Target.ORDERS, unit=Unit.ORDERS, value=1.0):
    return Series(target, "day", unit, START, tuple([value] * n), events)


def weekly(n, events, target=Target.ORDERS, unit=Unit.ORDERS, value=3.0):
    return Series(target, "week", unit, START, tuple([value] * n), events)


def test_insufficient_daily_history_explains_what_is_missing():
    r = rd.assess_series(daily(40, 50))
    assert r.status == ReadinessStatus.INSUFFICIENT and not r.ready
    assert (r.observations, r.required, r.shortfall) == (40, 84, 44)
    assert "40 of 84 complete days" in r.message and "44 more needed" in r.message


def test_exactly_at_the_threshold_is_ready_and_one_below_is_not():
    assert rd.assess_series(daily(84, 30)).ready
    assert not rd.assess_series(daily(83, 30)).ready
    assert rd.assess_series(weekly(24, 30)).ready
    assert not rd.assess_series(weekly(23, 30)).ready


def test_too_few_events_blocks_readiness_even_with_enough_days():
    r = rd.assess_series(daily(120, 29))
    assert not r.ready and r.shortfall == 0 and r.event_shortfall == 1
    assert "29 of 30 orders" in r.message


def test_empty_series_says_there_is_no_history():
    r = rd.assess_series(Series(Target.ORDERS, "day", Unit.ORDERS, START, (), 0))
    assert not r.ready and r.observations == 0 and r.first_date is None and r.last_date is None
    assert "no eligible history" in r.message and "84" in r.message
    assert r.completeness_pct is None and r.noise_floor_wape is None


def test_thresholds_come_from_the_policy():
    custom = Policy(daily=WindowRule("day", 7, 7, 14, 2, 10))
    assert rd.assess_series(daily(35, 10), custom).ready               # 7 + 14 + 2*7
    assert not rd.assess_series(daily(35, 10), DEFAULT_POLICY).ready


def test_zero_days_and_completeness():
    values = tuple([0.0] * 30 + [2.0] * 54)
    r = rd.assess_series(Series(Target.ORDERS, "day", Unit.ORDERS, START, values, 108))
    assert r.zero_steps == 30 and r.completeness_pct == round(100 * 54 / 84, 1) and r.longest_zero_run == 30


def test_noise_floor_is_only_for_count_targets():
    r = rd.assess_series(daily(84, 84, value=1.0))                     # mean 1 order/day
    assert abs(r.noise_floor_wape - 0.7979) < 1e-9
    big = rd.assess_series(daily(84, 8400, value=100.0))
    assert big.noise_floor_wape < r.noise_floor_wape                   # more volume -> lower irreducible error
    money = rd.assess_series(daily(84, 84, Target.GROSS_VALUE, Unit.PESO, 500.0))
    assert money.noise_floor_wape is None
    assert rd.poisson_noise_floor_wape(0) is None


def test_collections_event_wording():
    r = rd.assess_series(daily(120, 5, Target.COLLECTIONS, Unit.PESO, 10.0))
    assert "payment entries" in r.message


# ---- services ---------------------------------------------------------------------------------------

def entity(key, item_type, weeks, orders, label=None):
    s = Series(Target.SERVICE_DEMAND, "week", Unit.ORDERS, START, tuple([1.0] * weeks), orders, key, label or key)
    return dp.ServiceEntity(key, item_type, label or key, "load", s, None, orders, START)


def test_services_are_assessed_individually():
    ents = [entity("service:1", "service", 24, 20, "Wash"), entity("service:2", "service", 10, 30, "Dry"),
            entity("package:3", "package", 30, 10, "Fold pkg"), entity("addon:4", "addon", 40, 99, "Fabcon")]
    s = rd.assess_services(ents)
    by = {e.label: e for e in s.entities}
    assert by["Wash"].ready                                             # 24 weeks and 20 orders
    assert not by["Dry"].ready and "10 of 24 complete weeks" in by["Dry"].message
    assert not by["Fold pkg"].ready and "10 of 20 orders" in by["Fold pkg"].message
    assert s.total_entities == 3 and s.ready_entities == 1             # the add-on is not in the primary count
    assert s.status == ReadinessStatus.READY


def test_services_with_no_history_or_no_ready_entity():
    assert rd.assess_services([]).status == ReadinessStatus.INSUFFICIENT
    s = rd.assess_services([entity("service:1", "service", 5, 3)])
    assert s.status == ReadinessStatus.INSUFFICIENT and "none of 1" in s.message
    assert rd.assess_services([entity("addon:4", "addon", 40, 99)]).status == ReadinessStatus.INSUFFICIENT


# ---- overview --------------------------------------------------------------------------------------

def test_empty_database_overview_is_the_insufficient_data_state():
    o = rd.assess(dp.assemble(dp.RawData(), NOW), generated_at=datetime(2026, 11, 11, tzinfo=timezone.utc))
    assert o.status == ReadinessStatus.INSUFFICIENT and o.model_status == ModelStatus.INSUFFICIENT_DATA
    assert o.message == INSUFFICIENT_DATA_MESSAGE
    assert len(o.targets) == 6 and not any(t.ready for t in o.targets)
    assert o.as_dict()["model_status_label"] == "INSUFFICIENT DATA"


def test_small_real_history_is_reported_honestly():
    orders = {date(2026, 11, 1) + __import__("datetime").timedelta(days=i): (2, 200.0) for i in range(10)}
    o = rd.assess(dp.assemble(dp.RawData(orders_by_day=orders), NOW))
    t = {(x.target, x.granularity): x for x in o.targets}
    assert t[(Target.ORDERS, "day")].observations == 10 and t[(Target.ORDERS, "day")].shortfall == 74
    assert t[(Target.ORDERS, "week")].observations == 1 and not o.status == ReadinessStatus.READY


def test_daily_can_be_ready_while_weekly_is_not_yet():
    from datetime import timedelta
    # Mon Jun 1 .. Tue Nov 10 = 163 complete days but only 23 complete Mon-Sun weeks (24 needed).
    orders = {date(2026, 6, 1) + timedelta(days=i): (3, 300.0) for i in range(163)}
    o = rd.assess(dp.assemble(dp.RawData(orders_by_day=orders), NOW))
    got = [(t.target, t.granularity, t.observations, t.ready) for t in o.targets]
    assert got == [
        (Target.ORDERS, "day", 163, True), (Target.ORDERS, "week", 23, False),
        (Target.GROSS_VALUE, "day", 163, True), (Target.GROSS_VALUE, "week", 23, False),
        (Target.COLLECTIONS, "day", 0, False), (Target.COLLECTIONS, "week", 0, False)]     # no payment history
    assert o.status == ReadinessStatus.READY            # at least one target can be attempted


def test_enough_history_makes_everything_order_related_ready_without_claiming_a_model_exists():
    from datetime import timedelta
    orders = {date(2026, 5, 18) + timedelta(days=i): (3, 300.0) for i in range(177)}      # Mon May 18 .. Tue Nov 10
    o = rd.assess(dp.assemble(dp.RawData(orders_by_day=orders), NOW))
    assert [t.ready for t in o.targets] == [True, True, True, True, False, False]
    assert o.model_status == ModelStatus.READY_FOR_TRAINING and o.model_status != ModelStatus.TRAINED
    assert "does not guarantee" in o.message


def test_overview_is_json_serialisable_and_private():
    from datetime import timedelta
    orders = {date(2026, 9, 1) + timedelta(days=i): (1, 100.0) for i in range(70)}
    d = rd.assess(dp.assemble(dp.RawData(orders_by_day=orders, quality={"total_orders": 70, "eligible_orders": 70}), NOW)).as_dict()
    text = json.dumps(d)
    assert d["policy"]["daily"]["required_observations"] == 84 and d["policy"]["weekly"]["required_observations"] == 24
    for banned in ("customer", "phone", "email", "password", "token"):
        assert banned not in text.lower(), banned
    assert d["services"]["total_entities"] == 0 and d["ledger_start"] is None


def test_collections_issue_explains_the_tracking_start():
    from datetime import timedelta
    coll = {date(2026, 10, 20) + timedelta(days=i): (10.0, 0.0, 1, 0) for i in range(22)}
    o = rd.assess(dp.assemble(dp.RawData(collections_by_day=coll, ledger_start=date(2026, 10, 20)), NOW))
    t = {(x.target, x.granularity): x for x in o.targets}[(Target.COLLECTIONS, "day")]
    assert [i.code for i in t.issues] == ["collections_start"] and "Oct 20, 2026" in t.issues[0].message
    assert "not recorded" in t.issues[0].message
