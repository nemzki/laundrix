"""Tests for the disposal-risk model. Run with: pytest tests/analytics -q"""
from datetime import date, timedelta

import pytest

from app.analytics.importers.historical_transactions import HistoricalCsvError, parse_historical_csv
from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURES, feature_vector, previous_order_counts
from app.analytics.ml.policy import DISPOSAL_DAYS
from app.analytics.ml.training import load_training_rows, train_model
from app.extensions import db
from app.models import HistoricalTransaction, UnclaimedModelRun

HEADER = ("Date,No,Name,Kilo/Gram,Fold,Liquid Soap,Surf/Downy,Load Amount,Total Amount,"
          "Payment Status,Ready Date,Status,Claimed Date,Disposed Date,Status Source\n")


def test_feature_vector_matches_feature_names():
    vector = feature_vector(185, True, 2, date(2026, 11, 14))  # a Saturday
    assert len(vector) == len(FEATURES)
    assert vector == [185.0, 1.0, 2.0, 1.0]


def test_previous_order_counts_ignore_case_and_spaces():
    rows = [
        (1, "Lester", date(2026, 9, 1), 1),
        (2, " lester ", date(2026, 9, 2), 1),
        (3, None, date(2026, 9, 2), 2),
        (4, "Ana", date(2026, 9, 3), 1),
    ]
    assert previous_order_counts(rows) == {1: 0, 2: 1, 3: 0, 4: 0}


def test_model_round_trip_is_json_safe_and_learns_direction():
    import json

    x = [[100, 1, 5, 0]] * 30 + [[200, 0, 0, 1]] * 30
    y = [0] * 30 + [1] * 30
    params = ml.fit(x, y)
    json.dumps(params)
    assert ml.predict_probability(params, [200, 0, 0, 1]) > ml.predict_probability(params, [100, 1, 5, 0])


def _row(day, number, name, status, paid="paid"):
    ready = day
    return (
        f"{day},{number},{name},8 kls,20,15,15,135,185,{paid},{ready},{status},"
        f"{day + timedelta(days=1) if status == 'claimed' else ''},"
        f"{day + timedelta(days=DISPOSAL_DAYS) if status == 'disposed' else ''},recorded\n"
    )


def test_csv_with_outcomes_is_validated(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text(HEADER + _row(date(2026, 9, 1), 1, "Ana", "claimed"), encoding="utf-8")
    record = parse_historical_csv(path, "h.csv")[0]
    assert record["outcome_status"] == "claimed" and record["payment_status"] == "paid"


def test_csv_rejects_claimed_without_claimed_date(tmp_path):
    path = tmp_path / "h.csv"
    path.write_text(
        HEADER + "2026-09-01,1,Ana,8 kls,20,15,15,135,185,paid,2026-09-01,claimed,,,recorded\n",
        encoding="utf-8",
    )
    with pytest.raises(HistoricalCsvError, match="Claimed Date"):
        parse_historical_csv(path, "h.csv")


def _add_history(count, start=date(2026, 8, 1)):
    """Disposed orders are unpaid first-timers, so the data is learnable."""
    for i in range(count):
        disposed = i % 4 == 0
        day = start + timedelta(days=i // 3)
        db.session.add(HistoricalTransaction(
            transaction_date=day, source_transaction_no=i % 3 + 1, customer_name=f"C{i if disposed else i % 5}",
            raw_weight="8 kls", total_amount=185, payment_status="unpaid" if disposed else "paid",
            ready_date=day, outcome_status="disposed" if disposed else "claimed",
            claimed_date=None if disposed else day + timedelta(days=1),
            disposed_date=day + timedelta(days=DISPOSAL_DAYS) if disposed else None,
            status_source="recorded", import_source="t", source_row_key=f"k{i}",
        ))
    db.session.commit()


def test_training_refuses_small_data(app):
    _add_history(20)
    with pytest.raises(ValueError, match="mature orders"):
        train_model(as_of=date(2026, 12, 31))


def test_training_saves_one_active_model_and_excludes_immature_orders(app):
    _add_history(160)
    run = train_model(as_of=date(2026, 12, 31))
    assert run.is_active and run.version == 1 and run.labels_simulated is False
    assert run.metrics["test_disposed"] > 0

    again = train_model(as_of=date(2026, 12, 31))
    assert again.version == 2
    assert db.session.query(UnclaimedModelRun).filter_by(is_active=True).count() == 1

    # With an early as_of, later orders are not yet mature and must be left out.
    early = load_training_rows(as_of=date(2026, 8, 20))
    assert 0 < len(early) < 160
