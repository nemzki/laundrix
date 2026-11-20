"""Tests for the disposal-risk model. Run with: pytest tests/analytics -q"""
from datetime import date, timedelta

import pytest

from app.analytics.importers.historical_transactions import HistoricalCsvError, parse_historical_csv
from app.analytics.ml import model as ml
from app.analytics.ml.features import FEATURES, feature_vector, previous_order_counts
from app.analytics.ml.policy import DISPOSAL_DAYS

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
