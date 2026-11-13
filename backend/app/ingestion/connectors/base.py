"""The connector interface. Every data source turns its own format into ParsedRow objects.

The ingestion pipeline only ever sees ParsedRow, so replacing CSV uploads with open banking
(Basiq, Fiskil, Plaid...) means adding a connector; nothing downstream changes.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


class ParseError(ValueError):
    """The file isn't in the format the connector expects. The message is shown to the user."""


@dataclass
class ParsedRow:
    account_ref: str  # how the source names the account, e.g. "Card ending 3528"
    posted_date: date
    amount: Decimal  # negative = money out
    description: str
    merchant: str | None = None
    bank_type: str | None = None
    bank_category: str | None = None
    balance_after: Decimal | None = None
    is_pending: bool = False
    raw: dict = field(default_factory=dict)


class Connector(Protocol):
    source: str  # stored on the import batch, e.g. "nab_csv"
    institution: str  # e.g. "NAB"

    def parse(self, data: bytes) -> list[ParsedRow]: ...

    def account_kind(self, account_ref: str) -> str: ...

    def is_internal_transfer(self, row: ParsedRow) -> bool: ...
