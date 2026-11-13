"""NAB Internet Banking CSV exports (transaction accounts and credit cards).

Expected header, as NAB exports it:
    Date,Amount,Account Number,,Transaction Type,Transaction Details,Balance,Category,Merchant Name,Processed On
Rows with an empty "Processed On" are pending authorisations that the bank hasn't posted yet.
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.ingestion.connectors.base import ParsedRow, ParseError

REQUIRED = ["Date", "Amount", "Account Number", "Transaction Type", "Transaction Details"]
TRANSFER_TYPES = {"CREDIT CARD PAYMENT"}
TRANSFER_CATEGORIES = {"internal transfers"}
DATE_FORMATS = ("%d %b %y", "%d %b %Y", "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d")


def _date(value: str):
    v = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"Unrecognised date '{value}'.")


def _money(value: str, field: str, line: int) -> Decimal | None:
    v = value.strip().replace(",", "").replace("$", "")
    if v == "":
        return None
    try:
        return Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ParseError(f"Line {line}: '{value}' in {field} is not an amount.") from None


class NabCsvConnector:
    source = "nab_csv"
    institution = "NAB"

    def parse(self, data: bytes) -> list[ParsedRow]:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        reader = csv.reader(io.StringIO(text))
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            raise ParseError("The file is empty.") from None
        missing = [c for c in REQUIRED if c not in header]
        if missing:
            raise ParseError("This doesn't look like a NAB CSV export. Missing columns: " + ", ".join(missing) + ".")
        idx = {name: i for i, name in enumerate(header) if name}

        def col(row: list[str], name: str) -> str:
            i = idx.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        rows: list[ParsedRow] = []
        for line, row in enumerate(reader, start=2):
            if not row or not any(c.strip() for c in row):
                continue
            amount = _money(col(row, "Amount"), "Amount", line)
            if amount is None:
                raise ParseError(f"Line {line}: the amount is missing.")
            try:
                posted = _date(col(row, "Date"))
            except ParseError as e:
                raise ParseError(f"Line {line}: {e}") from None
            account = col(row, "Account Number")
            if not account:
                raise ParseError(f"Line {line}: the account is missing.")
            rows.append(
                ParsedRow(
                    account_ref=account,
                    posted_date=posted,
                    amount=amount,
                    description=col(row, "Transaction Details"),
                    merchant=col(row, "Merchant Name") or None,
                    bank_type=col(row, "Transaction Type") or None,
                    bank_category=col(row, "Category") or None,
                    balance_after=_money(col(row, "Balance"), "Balance", line),
                    is_pending="Processed On" in idx and col(row, "Processed On") == "",
                    raw={h: (row[i] if i < len(row) else "") for h, i in idx.items()},
                )
            )
        if not rows:
            raise ParseError("The file has a header but no transactions.")
        return rows

    def account_kind(self, account_ref: str) -> str:
        return "credit_card" if "card" in account_ref.lower() else "transaction"

    def is_internal_transfer(self, row: ParsedRow) -> bool:
        return (row.bank_type or "").upper() in TRANSFER_TYPES or (
            (row.bank_category or "").lower() in TRANSFER_CATEGORIES
        )


CONNECTORS = {"nab_csv": NabCsvConnector()}
