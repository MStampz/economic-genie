"""Any bank's CSV file, read with a column mapping the user sets up once.

The mapping says which column holds the date, the amount (or separate money-out and money-in
columns), the description and, optionally, the merchant, the bank's category, the balance and the
account. Files without an account column go into one named account.
"""

import csv
import hashlib
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.ingestion.connectors.base import ParsedRow, ParseError

DATE_FORMATS = {
    "DD/MM/YYYY": (
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d.%m.%Y",
        "%d %b %Y",
        "%d %b %y",
        "%d-%b-%Y",
        "%d-%b-%y",
    ),
    "MM/DD/YYYY": ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%b %d %Y", "%b %d, %Y"),
    "YYYY-MM-DD": ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"),
}


class CsvMapping(BaseModel):
    """How to read one CSV layout. Columns are named by their header (or "Column 3" without one)."""

    has_header: bool = True
    date: str = Field(min_length=1)
    date_format: Literal["auto", "DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] = "auto"
    amount: str | None = None
    debit: str | None = None  # money out, when the bank uses two columns
    credit: str | None = None  # money in
    flip_sign: bool = False  # some card exports show purchases as positive numbers
    description: list[str] = Field(min_length=1, max_length=3)
    merchant: str | None = None
    category: str | None = None
    balance: str | None = None
    account_column: str | None = None
    account_name: str | None = Field(default=None, max_length=100)
    account_kind: Literal["transaction", "credit_card"] = "transaction"
    institution: str = Field(default="Bank", min_length=1, max_length=60)

    @model_validator(mode="after")
    def check(self):
        if not self.amount and not (self.debit or self.credit):
            raise ValueError("Choose the amount column, or the money out and money in columns.")
        if not self.account_column and not (self.account_name or "").strip():
            raise ValueError("Choose the account column, or give the account a name.")
        return self

    def columns(self) -> list[str]:
        cols = [self.date, self.amount, self.debit, self.credit, self.merchant, self.category, self.balance]
        return [c for c in [*cols, *self.description, self.account_column] if c]


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def read_table(data: bytes, has_header: bool | None = None) -> tuple[list[str], list[list[str]], bool]:
    """Returns (column names, data rows, has_header). Guesses has_header when it isn't given."""
    text = decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if r and any(c.strip() for c in r)]
    if not rows:
        raise ParseError("The file is empty.")
    if has_header is None:
        has_header = _looks_like_header(rows[0])
    width = max(len(r) for r in rows[:50])
    if has_header:
        names = _unique_names(rows[0], width)
        body = rows[1:]
    else:
        names = [f"Column {i + 1}" for i in range(width)]
        body = rows
    return names, body, has_header


def header_signature(names: list[str], has_header: bool) -> str:
    key = "|".join(n.strip().lower() for n in names) if has_header else f"noheader:{len(names)}"
    return hashlib.sha256(key.encode()).hexdigest()


def _looks_like_header(row: list[str]) -> bool:
    """A header row has no dates or amounts in it."""
    for cell in row:
        c = cell.strip()
        if c and (parse_money(c) is not None or _any_date(c) is not None):
            return False
    return True


def _unique_names(row: list[str], width: int) -> list[str]:
    names, seen = [], {}
    for i in range(width):
        n = row[i].strip() if i < len(row) else ""
        n = n or f"Column {i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n} ({seen[n]})"
        else:
            seen[n] = 1
        names.append(n)
    return names


_MONEY_JUNK = re.compile(r"[\s$€£¥,]")
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}\s*|\s*[A-Z]{3}$")


def parse_money(value: str) -> Decimal | None:
    """Reads 1,234.56 / -12.00 / (12.00) / $12.00 / 12.00 DR / 12.00 CR. Returns None if it isn't money."""
    v = value.strip().replace("−", "-")
    if not v:
        return None
    negative = False
    upper = v.upper()
    if upper.endswith("DR"):
        negative, v = True, v[:-2]
    elif upper.endswith("CR"):
        v = v[:-2]
    v = _CURRENCY_CODE.sub("", v.strip())
    if v.startswith("(") and v.endswith(")"):
        negative, v = True, v[1:-1]
    v = _MONEY_JUNK.sub("", v)
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
        return None
    try:
        d = Decimal(v).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None
    return -abs(d) if negative else d


def _any_date(value: str) -> date | None:
    for fmts in DATE_FORMATS.values():
        for f in fmts:
            try:
                return datetime.strptime(value.strip(), f).date()
            except ValueError:
                continue
    return None


def detect_date_format(values: list[str]) -> str:
    """The first format family (day first, then month first, then ISO) that reads every value."""
    sample = [v.strip() for v in values if v.strip()][:200]
    for name, fmts in DATE_FORMATS.items():
        if sample and all(_parse_with(v, fmts) is not None for v in sample):
            return name
    return "DD/MM/YYYY"


def _parse_with(value: str, fmts: tuple[str, ...]) -> date | None:
    for f in fmts:
        try:
            return datetime.strptime(value, f).date()
        except ValueError:
            continue
    return None


def suggest_mapping(names: list[str], body: list[list[str]], has_header: bool) -> dict:
    """A best guess from common header names and the data, for the user to check."""

    def find(*words: str) -> str | None:
        for w in words:
            for n in names:
                if n.lower() == w:
                    return n
        for w in words:
            for n in names:
                if w in n.lower():
                    return n
        return None

    def values(col: str) -> list[str]:
        i = names.index(col)
        return [r[i] for r in body[:30] if i < len(r)]

    guess: dict = {"has_header": has_header}
    guess["date"] = find("date", "transaction date", "posted", "posting date", "value date")
    guess["debit"] = find("debit", "withdrawal", "money out", "paid out")
    guess["credit"] = find("credit", "deposit", "money in", "paid in")
    if guess["debit"] or guess["credit"]:
        guess["amount"] = None
    else:
        guess["amount"] = find("amount", "amount (aud)", "value", "transaction amount")
    desc = find("description", "transaction details", "details", "narrative", "memo", "payee", "reference")
    guess["description"] = [desc] if desc else []
    guess["merchant"] = find("merchant", "merchant name", "payee name")
    guess["category"] = find("category", "categories", "categor")
    guess["balance"] = find("balance", "running balance")
    guess["account_column"] = find("account number", "account", "card")
    # Without a header, fall back to the data: the first column of dates, then of amounts, then text.
    if not has_header or not guess["date"]:
        for n in names:
            vals = [v for v in values(n) if v.strip()]
            if vals and all(_any_date(v) for v in vals):
                guess["date"] = n
                break
    if not has_header or not (guess["amount"] or guess["debit"] or guess["credit"]):
        for n in names:
            vals = [v for v in values(n) if v.strip()]
            if n != guess.get("date") and vals and all(parse_money(v) is not None for v in vals):
                guess["amount"] = n
                break
    if not guess["description"]:
        for n in names:
            vals = [v for v in values(n) if v.strip()]
            if vals and not any(_any_date(v) or parse_money(v) is not None for v in vals):
                guess["description"] = [n]
                break
    if guess.get("date"):
        guess["date_format"] = detect_date_format(values(guess["date"]))
    return guess


class GenericCsvConnector:
    """Not registered by name: built per import from a mapping."""

    label = "CSV with your column mapping"

    def __init__(self, mapping: CsvMapping):
        self.mapping = mapping
        self.institution = mapping.institution.strip()
        self.source = "csv"

    def parse(self, data: bytes) -> list[ParsedRow]:
        m = self.mapping
        names, body, _ = read_table(data, m.has_header)
        unknown = [c for c in m.columns() if c not in names]
        if unknown:
            raise ParseError("These columns are not in the file: " + ", ".join(unknown) + ".")
        idx = {n: i for i, n in enumerate(names)}

        def col(row: list[str], name: str | None) -> str:
            if not name:
                return ""
            i = idx[name]
            return row[i].strip() if i < len(row) else ""

        date_values = [col(r, m.date) for r in body]
        family = m.date_format if m.date_format != "auto" else detect_date_format(date_values)
        fmts = DATE_FORMATS[family]
        start = 2 if m.has_header else 1
        rows: list[ParsedRow] = []
        for line, r in enumerate(body, start=start):
            raw_date = col(r, m.date)
            posted = _parse_with(raw_date, fmts)
            if posted is None:
                raise ParseError(f"Line {line}: '{raw_date}' is not a date in the {family} format.")
            amount = self._amount(r, col, line)
            description = " ".join(col(r, c) for c in m.description if col(r, c)) or "(no description)"
            account = col(r, m.account_column) if m.account_column else (m.account_name or "").strip()
            if not account:
                raise ParseError(f"Line {line}: the account is missing.")
            balance_text = col(r, m.balance)
            rows.append(
                ParsedRow(
                    account_ref=account,
                    posted_date=posted,
                    amount=amount,
                    description=description,
                    merchant=col(r, m.merchant) or None,
                    bank_category=col(r, m.category) or None,
                    balance_after=parse_money(balance_text) if balance_text else None,
                    raw={n: (r[i] if i < len(r) else "") for n, i in idx.items()},
                )
            )
        if not rows:
            raise ParseError("The file has no transactions.")
        return rows

    def _amount(self, r, col, line: int) -> Decimal:
        m = self.mapping
        if m.amount:
            text = col(r, m.amount)
            value = parse_money(text)
            if value is None:
                raise ParseError(f"Line {line}: '{text}' is not an amount.")
        else:
            out_text, in_text = col(r, m.debit), col(r, m.credit)
            out, inn = parse_money(out_text) if out_text else None, parse_money(in_text) if in_text else None
            if (out_text and out is None) or (in_text and inn is None) or (out is None and inn is None):
                raise ParseError(f"Line {line}: no amount found in the money out or money in column.")
            value = (inn or Decimal("0")) - abs(out or Decimal("0"))
        return -value if m.flip_sign else value

    def account_kind(self, account_ref: str) -> str:
        return self.mapping.account_kind

    def is_internal_transfer(self, row: ParsedRow) -> bool:
        # Only an explicit "internal" transfer: a plain "Transfers" category also covers money sent to other people.
        return (row.bank_category or "").strip().lower() in {"internal transfers", "internal transfer"}
