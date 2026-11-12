"""Database-backed ML data preparation.  Needs the Flask app fixtures (run with pytest).

Reference moment: NOW = 2026-11-11 04:00 UTC = Wed 12:00 in Manila (see test_data_preparation.py).
"""
import json
from datetime import date, datetime, timedelta

from app.analytics.ml import data_preparation as dp
from app.analytics.ml import data_source as ds
from app.analytics.ml import readiness as rd
from app.analytics.ml.policy import DEFAULT_POLICY
from app.extensions import db
from app.models import Service

from tests.analytics import factories as f

NOW = datetime(2026, 11, 11, 4, 0)
P = DEFAULT_POLICY


def customer(name="Ana Cruz"):
    return f.make_customer(name, f.local(2026, 10, 1, 9))


def orders_by_day():
    return ds.fetch_orders_by_day(NOW, P)


# ---- eligibility -------------------------------------------------------------------------------

def test_only_received_valid_orders_are_eligible(app, payment_methods):
    c = customer()
    f.make_order(c, 100, f.local(2026, 11, 2, 9))                                        # A: normal, received
    f.make_order(c, 110, f.local(2026, 11, 2, 10), received=False)                       # B: slip issued, never confirmed
    f.make_order(c, 120, f.local(2026, 11, 3, 12), received_at=f.local(2026, 11, 3, 11))  # C: received an hour BEFORE created
    f.make_order(c, 130, f.local(2026, 11, 4, 12), received_at=f.local(2026, 11, 5, 12) + timedelta(days=30))  # D: received in the future
    legacy_created = f.local(2026, 11, 6, 10)
    f.make_order(c, 140, legacy_created, received_at=legacy_created - timedelta(milliseconds=20))  # E: legacy path, ms earlier
    db.session.commit()

    q = ds.fetch_quality(NOW, P)
    assert q["total_orders"] == 5 and q["awaiting_receipt"] == 1
    assert q["invalid_received_before_created"] == 1 and q["invalid_received_future"] == 1
    assert q["eligible_orders"] == 2                                                     # A and E
    days = orders_by_day()
    assert set(days) == {date(2026, 11, 2), date(2026, 11, 6)}
    assert days[date(2026, 11, 2)] == (1, 100.0) and days[date(2026, 11, 6)] == (1, 140.0)


def test_the_forecasting_date_is_received_at_not_created_at(app, payment_methods):
    c = customer()
    # slip issued Oct 31 evening, laundry actually received on Nov 2
    f.make_order(c, 200, f.local(2026, 10, 31, 22), received_at=f.local(2026, 11, 2, 9))
    db.session.commit()
    days = orders_by_day()
    assert list(days) == [date(2026, 11, 2)] and days[date(2026, 11, 2)] == (1, 200.0)


def test_philippine_midnight_boundary_on_received_at(app, payment_methods):
    c = customer()
    f.make_order(c, 10, f.local(2026, 11, 1, 9), received_at=f.local(2026, 11, 2, 23, 59, 59))   # 15:59:59 UTC
    f.make_order(c, 20, f.local(2026, 11, 1, 9), received_at=f.local(2026, 11, 3, 0, 0, 0))      # 16:00:00 UTC
    db.session.commit()
    days = orders_by_day()
    assert days[date(2026, 11, 2)] == (1, 10.0) and days[date(2026, 11, 3)] == (1, 20.0)


def test_every_status_counts_once_received(app, payment_methods):
    c = customer()
    for i, status in enumerate(["order_received", "pending_processing", "processing", "ready_for_pickup", "picked_up", "completed"]):
        f.make_order(c, 50, f.local(2026, 11, 2, 9 + i), status)
    db.session.commit()
    assert orders_by_day()[date(2026, 11, 2)] == (6, 300.0)


def test_new_eligible_records_are_included_without_any_code_change(app, payment_methods):
    c = customer()
    f.make_order(c, 100, f.local(2026, 11, 2, 9))
    db.session.commit()
    first = dp.prepare_all(NOW)
    f.make_order(c, 100, f.local(2026, 11, 3, 9))                                        # a record added later
    f.make_order(c, 100, f.local(2026, 11, 3, 10), received=False)                       # an ineligible one
    db.session.commit()
    second = dp.prepare_all(NOW)
    assert first.orders_daily.events == 1 and second.orders_daily.events == 2
    assert second.quality["eligible_orders"] == 2 and second.quality["awaiting_receipt"] == 1


def test_gross_value_comes_from_order_totals_not_payments(app, payment_methods):
    c = customer()
    o = f.make_order(c, 500, f.local(2026, 11, 2, 9))
    f.add_payment(o, 120, f.local(2026, 11, 2, 10))                                      # partial payment
    db.session.commit()
    p = dp.prepare_all(NOW)
    assert p.gross_daily.values[0] == 500.0                                              # billed value
    assert p.collections_daily.values[0] == 120.0                                        # money actually collected


# ---- ledger -----------------------------------------------------------------------------------------

def test_collections_net_reversals_and_ignore_order_eligibility(app, payment_methods):
    c = customer()
    stub = f.make_order(c, 100, f.local(2026, 11, 2, 9), received=False)                 # never received...
    pay = f.add_payment(stub, 100, f.local(2026, 11, 2, 10))                             # ...but money was taken
    other = f.make_order(c, 80, f.local(2026, 11, 3, 9))
    f.add_payment(other, 50, f.local(2026, 11, 3, 10))
    f.add_reversal(pay, f.local(2026, 11, 4, 9))
    db.session.commit()
    got = ds.fetch_collections_by_day()
    assert got[date(2026, 11, 2)] == (100.0, 0.0, 1, 0)
    assert got[date(2026, 11, 3)] == (50.0, 0.0, 1, 0)
    assert got[date(2026, 11, 4)] == (0.0, 100.0, 0, 1)          # a reversal lands on the day it was recorded
    assert orders_by_day() == {date(2026, 11, 3): (1, 80.0)}     # the stub is not demand, its cash is still cash


def test_ledger_start_is_the_earlier_of_first_payment_and_first_tracked_order(app, payment_methods):
    assert ds.fetch_ledger_start() is None
    c = customer()
    legacy = f.make_order(c, 100, f.local(2026, 10, 1, 9), tracked=False)
    db.session.commit()
    assert ds.fetch_ledger_start() is None                                               # untracked orders prove nothing
    tracked = f.make_order(c, 100, f.local(2026, 10, 28, 9))
    f.add_payment(tracked, 50, f.local(2026, 10, 30, 9))
    db.session.commit()
    assert ds.fetch_ledger_start() == date(2026, 10, 28)


# ---- services --------------------------------------------------------------------------------------------

def test_service_rows_use_snapshots_and_survive_deleted_catalog_rows(app, payment_methods):
    svc = Service(code="wash", name="Wash", price=80)
    db.session.add(svc)
    db.session.flush()
    c = customer()
    f.make_order(c, 300, f.local(2026, 11, 2, 9), items=[
        {"item_type": "service", "name": "Wash", "quantity": 2, "unit": "load", "line_total": 160, "service_id": svc.id},
        {"item_type": "package", "name": "Wash, Dry & Fold", "quantity": 1, "unit": "package", "line_total": 100,
         "description": "Clothes · 3KG-5KG (small)"},                                      # package row deleted: id NULL
        {"item_type": "addon", "name": "Fabcon", "quantity": 2, "unit": "pc", "line_total": 40}])
    f.make_order(c, 80, f.local(2026, 11, 2, 11), received=False, items=[
        {"item_type": "service", "name": "Wash", "quantity": 1, "unit": "load", "line_total": 80, "service_id": svc.id}])
    db.session.commit()

    rows = ds.fetch_service_rows(NOW, P)
    assert len(rows) == 3                                                                # the unreceived order's item is excluded
    by_type = {r["item_type"]: r for r in rows}
    assert by_type["service"]["orders"] == 1 and by_type["service"]["quantity"] == 2.0 and by_type["service"]["service_id"] == svc.id
    assert by_type["package"]["package_id"] is None and by_type["package"]["description"].startswith("Clothes")
    assert by_type["addon"]["item_type"] == "addon"

    keys = {dp.entity_key(r["item_type"], r["service_id"], r["package_id"], r["addon_id"], r["name"], r["description"]) for r in rows}
    assert keys == {f"service:{svc.id}", "package:~clothes · 3kg-5kg (small)", "addon:~fabcon"}


def test_multi_item_order_counts_as_one_order_per_service(app, payment_methods):
    c = customer()
    f.make_order(c, 200, f.local(2026, 11, 2, 9), items=[
        {"item_type": "service", "name": "Wash", "quantity": 1, "unit": "load", "line_total": 80},
        {"item_type": "service", "name": "Dry", "quantity": 1, "unit": "load", "line_total": 60},
        {"item_type": "addon", "name": "Fabcon", "quantity": 1, "unit": "pc", "line_total": 20}])
    db.session.commit()
    assert orders_by_day()[date(2026, 11, 2)] == (1, 200.0)                              # joins do not multiply orders
    assert {r["name"]: r["orders"] for r in ds.fetch_service_rows(NOW, P)} == {"Wash": 1, "Dry": 1, "Fabcon": 1}


# ---- data quality --------------------------------------------------------------------------------------------

def test_possible_duplicates_and_empty_orders_are_flagged_not_removed(app, payment_methods):
    c, other = customer(), customer("Ben Reyes")
    f.make_order(c, 100, f.local(2026, 11, 2, 9))
    f.make_order(c, 100, f.local(2026, 11, 2, 15))                                       # same customer, total and day
    f.make_order(c, 110, f.local(2026, 11, 2, 16))                                       # different total: not a duplicate
    f.make_order(other, 100, f.local(2026, 11, 2, 17), items=[("service", "Wash", 1, "load", 100)])
    db.session.commit()
    q = ds.fetch_quality(NOW, P)
    assert q["possible_duplicate_groups"] == 1 and q["eligible_orders"] == 4
    assert q["eligible_without_items"] == 3
    assert orders_by_day()[date(2026, 11, 2)][0] == 4                                    # nothing was dropped


# ---- end to end + privacy + CLI -----------------------------------------------------------------------------

def test_readiness_on_an_empty_database_is_the_insufficient_state(app, payment_methods):
    report = rd.assess(dp.prepare_all(NOW))
    assert report.status == "insufficient_data" and "sufficient historical records" in report.message
    assert all(t.observations == 0 for t in report.targets)


def test_readiness_reports_real_counts_for_a_small_history(app, payment_methods):
    c = customer()
    for i in range(5):
        f.make_order(c, 100 + i, f.local(2026, 11, 1 + i, 9))
    db.session.commit()
    report = rd.assess(dp.prepare_all(NOW))
    t = {(x.target, x.granularity): x for x in report.targets}[("orders", "day")]
    assert t.observations == 10 and t.events == 5 and t.shortfall == 74 and not t.ready      # Nov 1..Nov 10


def test_nothing_personal_reaches_the_ml_layer_or_its_output(app, payment_methods):
    c = f.make_customer("Zacharias Quimpo", f.local(2026, 10, 1, 9))
    o = f.make_order(c, 100, f.local(2026, 11, 2, 9), items=[("service", "Wash", 1, "load", 100)])
    f.add_payment(o, 100, f.local(2026, 11, 2, 10))
    db.session.commit()
    prepared = dp.prepare_all(NOW)
    text = json.dumps(rd.assess(prepared).as_dict()) + repr(prepared)
    assert "Zacharias" not in text and "Quimpo" not in text and "TESTCONTACT" not in text and c.contact_normalized not in text


def test_cli_prints_readiness_and_changes_nothing(app, payment_methods):
    c = customer()
    f.make_order(c, 100, f.local(2026, 11, 2, 9))
    db.session.commit()
    before = db.session.scalar(db.select(db.func.count()).select_from(db.metadata.tables["orders"]))
    runner = app.test_cli_runner()
    result = runner.invoke(args=["analytics-readiness"])
    assert result.exit_code == 0, result.output
    assert "INSUFFICIENT DATA" in result.output and "sufficient historical records" in result.output
    assert "Zacharias" not in result.output and "Ana Cruz" not in result.output
    as_json = runner.invoke(args=["analytics-readiness", "--json"])
    assert as_json.exit_code == 0 and json.loads(as_json.output)["status"] == "insufficient_data"
    assert db.session.scalar(db.select(db.func.count()).select_from(db.metadata.tables["orders"])) == before
