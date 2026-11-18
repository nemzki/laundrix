
import csv
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import HistoricalTransaction
from app.analytics.importers.service import (
    import_historical_transactions,
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


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(HEADERS)
        writer.writerows(rows)


def valid_row(number=1, name="Lester", total="185"):
    return [
        "2026-09-11",
        str(number),
        name,
        "8 kls",
        "20",
        "15",
        "15",
        "135",
        total,
    ]


def count_historical_records():
    return db.session.query(HistoricalTransaction).count()


def test_dry_run_does_not_insert_records(app, tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row(2)])

    result = import_historical_transactions(csv_path)

    assert result["total_rows"] == 2
    assert result["inserted"] == 2
    assert result["skipped"] == 0
    assert result["executed"] is False
    assert count_historical_records() == 0


def test_execute_inserts_all_valid_records(app, tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row(2)])

    result = import_historical_transactions(
        csv_path,
        execute=True,
    )

    assert result["inserted"] == 2
    assert result["executed"] is True
    assert count_historical_records() == 2


def test_reimport_skips_identical_records(app, tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row(2)])

    import_historical_transactions(csv_path, execute=True)

    result = import_historical_transactions(
        csv_path,
        execute=True,
    )

    assert result["inserted"] == 0
    assert result["skipped"] == 2
    assert count_historical_records() == 2


def test_conflicting_existing_record_stops_import(app, tmp_path):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row(2)])

    import_historical_transactions(csv_path, execute=True)

    changed_csv = tmp_path / "changed.csv"
    write_csv(
        changed_csv,
        [
            valid_row(name="Different Name"),
            valid_row(3, name="New Customer"),
        ],
    )

    with pytest.raises(ValueError, match="conflicting existing"):
        import_historical_transactions(
            changed_csv,
            import_source="history.csv",
            execute=True,
        )

    assert count_historical_records() == 2


def test_database_failure_rolls_back_import(app, tmp_path, monkeypatch):
    csv_path = tmp_path / "history.csv"
    write_csv(csv_path, [valid_row(), valid_row(2)])

    def fail_commit():
        raise RuntimeError("Simulated database failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)

    with pytest.raises(RuntimeError, match="Simulated database failure"):
        import_historical_transactions(
            csv_path,
            execute=True,
        )

    db.session.remove()
    assert count_historical_records() == 0
