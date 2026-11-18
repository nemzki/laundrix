
import csv

import pytest

from app.analytics.importers.historical_transactions import (
    HistoricalCsvError,
    parse_historical_csv,
)


HEADERS = [
    "Date",
    "No",
    "Name",
    "Kilo/Gram",
    "Fold",
    "Liquid Soap",
    "Surf/Downy",
    "Load Amount",
    "Total Amount",
]


def write_csv(path, rows, headers=None):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(headers or HEADERS)
        writer.writerows(rows)


def valid_row():
    return [
        "2026-09-11",
        "1",
        "Lester",
        "8 kls",
        "20",
        "15",
        "15",
        "135",
        "185",
    ]


def test_parses_valid_historical_transaction(tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row()])

    records = parse_historical_csv(csv_path, "history.csv")

    assert len(records) == 1
    assert records[0]["customer_name"] == "Lester"
    assert records[0]["raw_weight"] == "8 kls"
    assert records[0]["total_amount"].to_eng_string() == "185.00"
    assert records[0]["payment_status"] == "unknown"
    assert records[0]["import_source"] == "history.csv"
    assert records[0]["source_row_key"].startswith("historical:")


def test_preserves_non_numeric_weight_labels(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = valid_row()
    row[3] = "Comp."
    write_csv(csv_path, [row])

    records = parse_historical_csv(csv_path, "history.csv")

    assert records[0]["raw_weight"] == "Comp."


def test_rejects_duplicate_date_and_transaction_number(tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row()])

    with pytest.raises(HistoricalCsvError, match="duplicate transaction"):
        parse_historical_csv(csv_path, "history.csv")


def test_rejects_missing_required_column(tmp_path):
    csv_path = tmp_path / "history.csv"
    incomplete_headers = HEADERS[:-1]
    incomplete_row = valid_row()[:-1]
    write_csv(csv_path, [incomplete_row], incomplete_headers)

    with pytest.raises(HistoricalCsvError, match="Missing required columns"):
        parse_historical_csv(csv_path, "history.csv")


def test_rejects_invalid_date(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = valid_row()
    row[0] = "not-a-date"
    write_csv(csv_path, [row])

    with pytest.raises(HistoricalCsvError, match="invalid date"):
        parse_historical_csv(csv_path, "history.csv")


def test_rejects_invalid_monetary_value(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = valid_row()
    row[8] = "invalid"
    write_csv(csv_path, [row])

    with pytest.raises(HistoricalCsvError, match="invalid amount"):
        parse_historical_csv(csv_path, "history.csv")


def test_rejects_negative_monetary_value(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = valid_row()
    row[4] = "-20"
    write_csv(csv_path, [row])

    with pytest.raises(HistoricalCsvError, match="non-negative"):
        parse_historical_csv(csv_path, "history.csv")


def test_same_source_and_transaction_produce_stable_row_key(tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row()])

    first = parse_historical_csv(csv_path, "history.csv")
    second = parse_historical_csv(csv_path, "history.csv")

    assert first[0]["source_row_key"] == second[0]["source_row_key"]

def test_rejects_amount_exceeding_database_precision(tmp_path):
    csv_path = tmp_path / "history.csv"
    row = valid_row()
    row[8] = "100000000.00"
    write_csv(csv_path, [row])

    with pytest.raises(HistoricalCsvError, match="exceeds the maximum"):
        parse_historical_csv(csv_path, "history.csv")