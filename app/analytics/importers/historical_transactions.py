"""Reads and validates the historical transactions CSV file before it is imported.

Checks the required columns, each amount and date, and reports clear line-numbered errors."""

import csv
import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


# The original 9 columns. Every file must have these.
REQUIRED_COLUMNS = (
    "Date",
    "No",
    "Name",
    "Kilo/Gram",
    "Fold",
    "Liquid Soap",
    "Surf/Downy",
    "Load Amount",
    "Total Amount",
)

# Optional columns used by the unclaimed-order prediction model.  A file may leave all of
# them out (old format).  If "Status" is present, the other five must be present too.
OUTCOME_COLUMNS = (
    "Payment Status",
    "Ready Date",
    "Status",
    "Claimed Date",
    "Disposed Date",
    "Status Source",
)

MONEY_COLUMNS = {
    "Fold": "fold_amount",
    "Liquid Soap": "liquid_soap_amount",
    "Surf/Downy": "surf_downy_amount",
    "Load Amount": "load_amount",
    "Total Amount": "total_amount",
}

PAYMENT_STATUSES = ("paid", "unpaid")
OUTCOME_STATUSES = ("claimed", "unclaimed", "disposed")
STATUS_SOURCES = ("recorded", "simulated")


class HistoricalCsvError(ValueError):
    """Raised when a historical transaction CSV is invalid."""


def _parse_amount(value, line_number, column):
    """Convert a CSV amount to a Decimal.

    Rejects empty, non-numeric, negative, too-large or more-than-2-decimal values, naming the line and column."""
    value = value.strip()

    if not value:
        raise HistoricalCsvError(
            f"Line {line_number}: {column} is empty."
        )

    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise HistoricalCsvError(
            f"Line {line_number}: invalid amount in {column}: {value!r}."
        ) from exc

    if not amount.is_finite() or amount < 0:
        raise HistoricalCsvError(
            f"Line {line_number}: {column} must be a finite, "
            "non-negative amount."
        )

    if amount > Decimal("99999999.99"):
        raise HistoricalCsvError(
            f"Line {line_number}: {column} exceeds the maximum "
            "supported amount of 99999999.99."
        )

    if amount.as_tuple().exponent < -2:
        raise HistoricalCsvError(
            f"Line {line_number}: {column} cannot have more than "
            "two decimal places."
        )

    return amount.quantize(Decimal("0.01"))


def _parse_optional_date(value, line_number, column):
    """Convert a YYYY-MM-DD CSV value to a date; an empty value gives None and a bad value raises a clear error."""
    value = value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HistoricalCsvError(
            f"Line {line_number}: invalid {column} {value!r}; expected YYYY-MM-DD."
        ) from exc


def _parse_outcome(values, transaction_date, line_number):
    """Validate the optional outcome columns of one row and return model field values."""
    payment = values["Payment Status"].strip().lower() or "unknown"
    if payment != "unknown" and payment not in PAYMENT_STATUSES:
        raise HistoricalCsvError(
            f"Line {line_number}: Payment Status must be paid or unpaid, got {payment!r}."
        )

    status = values["Status"].strip().lower() or "unknown"
    if status != "unknown" and status not in OUTCOME_STATUSES:
        raise HistoricalCsvError(
            f"Line {line_number}: Status must be claimed, unclaimed or disposed, got {status!r}."
        )

    source = values["Status Source"].strip().lower() or "unknown"
    if source != "unknown" and source not in STATUS_SOURCES:
        raise HistoricalCsvError(
            f"Line {line_number}: Status Source must be recorded or simulated, got {source!r}."
        )

    ready = _parse_optional_date(values["Ready Date"], line_number, "Ready Date")
    claimed = _parse_optional_date(values["Claimed Date"], line_number, "Claimed Date")
    disposed = _parse_optional_date(values["Disposed Date"], line_number, "Disposed Date")

    if status == "unknown":
        if claimed or disposed:
            raise HistoricalCsvError(
                f"Line {line_number}: Claimed/Disposed Date given but Status is empty."
            )
    else:
        if ready is None:
            raise HistoricalCsvError(f"Line {line_number}: Ready Date is required when Status is set.")
        if ready < transaction_date:
            raise HistoricalCsvError(f"Line {line_number}: Ready Date is before the transaction Date.")
        if status == "claimed" and (claimed is None or disposed is not None or claimed < ready):
            raise HistoricalCsvError(
                f"Line {line_number}: a claimed order needs a Claimed Date on/after Ready Date "
                "and no Disposed Date."
            )
        if status == "disposed" and (disposed is None or claimed is not None or disposed < ready):
            raise HistoricalCsvError(
                f"Line {line_number}: a disposed order needs a Disposed Date on/after Ready Date "
                "and no Claimed Date."
            )
        if status == "unclaimed" and (claimed is not None or disposed is not None):
            raise HistoricalCsvError(
                f"Line {line_number}: an unclaimed order must not have a Claimed or Disposed Date."
            )

    return {
        "payment_status": payment,
        "ready_date": ready,
        "outcome_status": status,
        "claimed_date": claimed,
        "disposed_date": disposed,
        "status_source": source,
    }


def parse_historical_csv(file_path, import_source):
    """Validate a historical CSV and return normalized records.

    This function performs no database operations.
    """
    path = Path(file_path)
    import_source = str(import_source).strip()

    if not path.is_file():
        raise HistoricalCsvError(f"CSV file does not exist: {path}")

    if not import_source or len(import_source) > 255:
        raise HistoricalCsvError(
            "Import source must contain 1 to 255 characters."
        )

    records = []
    seen_transactions = set()

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            reader = csv.reader(csv_file)

            headers = next(reader, None)

            if not headers:
                raise HistoricalCsvError("CSV file is empty.")

            headers = [header.strip() for header in headers]

            if len(headers) != len(set(headers)):
                raise HistoricalCsvError(
                    "CSV contains duplicate column headers."
                )

            missing = [
                column
                for column in REQUIRED_COLUMNS
                if column not in headers
            ]

            if missing:
                raise HistoricalCsvError(
                    "Missing required columns: "
                    + ", ".join(missing)
                )

            has_outcomes = "Status" in headers
            if has_outcomes:
                missing_outcomes = [c for c in OUTCOME_COLUMNS if c not in headers]
                if missing_outcomes:
                    raise HistoricalCsvError(
                        "Missing outcome columns: " + ", ".join(missing_outcomes)
                    )

            wanted = REQUIRED_COLUMNS + (OUTCOME_COLUMNS if has_outcomes else ())
            column_indexes = {
                column: headers.index(column)
                for column in wanted
            }

            for line_number, row in enumerate(reader, start=2):
                if not row or all(not value.strip() for value in row):
                    continue

                if len(row) != len(headers):
                    raise HistoricalCsvError(
                        f"Line {line_number}: expected {len(headers)} "
                        f"columns but found {len(row)}."
                    )

                values = {
                    column: row[index].strip()
                    for column, index in column_indexes.items()
                }

                try:
                    transaction_date = date.fromisoformat(values["Date"])
                except ValueError as exc:
                    raise HistoricalCsvError(
                        f"Line {line_number}: invalid date "
                        f"{values['Date']!r}; expected YYYY-MM-DD."
                    ) from exc

                try:
                    transaction_no = int(values["No"])
                except ValueError as exc:
                    raise HistoricalCsvError(
                        f"Line {line_number}: transaction number "
                        "must be an integer."
                    ) from exc

                if transaction_no < 1:
                    raise HistoricalCsvError(
                        f"Line {line_number}: transaction number "
                        "must be positive."
                    )

                transaction_key = (transaction_date, transaction_no)

                if transaction_key in seen_transactions:
                    raise HistoricalCsvError(
                        f"Line {line_number}: duplicate transaction "
                        f"{transaction_date} / No. {transaction_no}."
                    )

                seen_transactions.add(transaction_key)

                customer_name = values["Name"] or None
                raw_weight = values["Kilo/Gram"] or None

                if customer_name and len(customer_name) > 150:
                    raise HistoricalCsvError(
                        f"Line {line_number}: customer name exceeds "
                        "150 characters."
                    )

                if raw_weight and len(raw_weight) > 30:
                    raise HistoricalCsvError(
                        f"Line {line_number}: Kilo/Gram exceeds "
                        "30 characters."
                    )

                record = {
                    "transaction_date": transaction_date,
                    "source_transaction_no": transaction_no,
                    "customer_name": customer_name,
                    "raw_weight": raw_weight,
                    "payment_status": "unknown",
                    "import_source": import_source,
                }

                for csv_column, model_column in MONEY_COLUMNS.items():
                    record[model_column] = _parse_amount(
                        values[csv_column],
                        line_number,
                        csv_column,
                    )

                if has_outcomes:
                    record.update(_parse_outcome(values, transaction_date, line_number))

                key_material = (
                    f"{import_source}|"
                    f"{transaction_date.isoformat()}|"
                    f"{transaction_no}"
                )

                record["source_row_key"] = (
                    "historical:"
                    + hashlib.sha256(
                        key_material.encode("utf-8")
                    ).hexdigest()
                )

                records.append(record)

    except UnicodeDecodeError as exc:
        raise HistoricalCsvError(
            "CSV must use UTF-8 encoding."
        ) from exc
    except csv.Error as exc:
        raise HistoricalCsvError(
            f"Could not read CSV: {exc}"
        ) from exc

    if not records:
        raise HistoricalCsvError(
            "CSV contains no transaction records."
        )

    return records
