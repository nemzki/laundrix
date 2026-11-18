
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import HistoricalTransaction

from app.analytics.importers.historical_transactions import (
    parse_historical_csv,
)


COMPARISON_FIELDS = (
    "customer_name",
    "raw_weight",
    "fold_amount",
    "liquid_soap_amount",
    "surf_downy_amount",
    "load_amount",
    "total_amount",
    "payment_status",
    "source_row_key",
)


def import_historical_transactions(
    file_path,
    import_source=None,
    execute=False,
):
    """Validate and optionally import historical transactions.

    Dry-run is the default. Existing identical records are skipped.
    Conflicting records stop the import before any writes occur.
    """
    path = Path(file_path)

    if import_source is None:
        import_source = path.name
    else:
        import_source = str(import_source).strip()

    records = parse_historical_csv(path, import_source)

    existing_records = HistoricalTransaction.query.filter_by(
        import_source=import_source
    ).all()

    existing_by_key = {
        (record.transaction_date, record.source_transaction_no): record
        for record in existing_records
    }

    to_insert = []
    skipped = 0
    conflicts = []

    for record in records:
        key = (
            record["transaction_date"],
            record["source_transaction_no"],
        )

        existing = existing_by_key.get(key)

        if existing is None:
            to_insert.append(record)
            continue

        identical = all(
            getattr(existing, field) == record[field]
            for field in COMPARISON_FIELDS
        )

        if identical:
            skipped += 1
        else:
            conflicts.append(key)

    if conflicts:
        examples = ", ".join(
            f"{transaction_date} / No. {transaction_no}"
            for transaction_date, transaction_no in conflicts[:5]
        )
        raise ValueError(
            f"Import stopped: {len(conflicts)} conflicting existing "
            f"record(s). Examples: {examples}"
        )

    result = {
        "total_rows": len(records),
        "inserted": len(to_insert),
        "skipped": skipped,
        "executed": execute,
        "import_source": import_source,
    }

    if not execute:
        return result

    try:
        for record in to_insert:
            db.session.add(HistoricalTransaction(**record))

        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise

    return result
