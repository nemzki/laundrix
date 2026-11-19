from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db
from app.models import HistoricalTransaction

from app.analytics.importers.historical_transactions import (
    parse_historical_csv,
)


# If any of these differ from what is already stored, the import stops (possible wrong file).
BASE_FIELDS = (
    "customer_name",
    "raw_weight",
    "fold_amount",
    "liquid_soap_amount",
    "surf_downy_amount",
    "load_amount",
    "total_amount",
    "source_row_key",
)

# Outcome fields may be filled in later by re-importing an updated CSV for the same source.
# They are only compared/updated when the CSV actually contains the outcome columns, so
# re-importing an old 9-column file can never wipe outcomes that are already stored.
OUTCOME_FIELDS = (
    "payment_status",
    "ready_date",
    "outcome_status",
    "claimed_date",
    "disposed_date",
    "status_source",
)


def import_historical_transactions(
    file_path,
    import_source=None,
    execute=False,
):
    """Validate and optionally import historical transactions.

    Dry-run is the default. Identical records are skipped. Existing records whose outcome
    columns differ are updated. Existing records whose base fields differ stop the import
    before any writes occur.
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
    to_update = []
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

        if any(getattr(existing, field) != record[field] for field in BASE_FIELDS):
            conflicts.append(key)
            continue

        has_outcomes = "outcome_status" in record
        outcome_changes = {
            field: record[field]
            for field in OUTCOME_FIELDS
            if has_outcomes and getattr(existing, field) != record[field]
        }
        if outcome_changes:
            to_update.append((existing, outcome_changes))
        else:
            skipped += 1

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
        "updated": len(to_update),
        "skipped": skipped,
        "executed": execute,
        "import_source": import_source,
    }

    if not execute:
        return result

    try:
        for record in to_insert:
            db.session.add(HistoricalTransaction(**record))

        for existing, changes in to_update:
            for field, value in changes.items():
                setattr(existing, field, value)

        db.session.commit()

    except SQLAlchemyError:
        db.session.rollback()
        raise

    except Exception:
        db.session.rollback()
        raise

    return result
