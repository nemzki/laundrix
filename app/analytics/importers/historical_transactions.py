
import csv
import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path


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

MONEY_COLUMNS = {
    "Fold": "fold_amount",
    "Liquid Soap": "liquid_soap_amount",
    "Surf/Downy": "surf_downy_amount",
    "Load Amount": "load_amount",
    "Total Amount": "total_amount",
}


class HistoricalCsvError(ValueError):
    """Raised when a historical transaction CSV is invalid."""


def _parse_amount(value, line_number, column):
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

            column_indexes = {
                column: headers.index(column)
                for column in REQUIRED_COLUMNS
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
