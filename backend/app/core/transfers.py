"""Money moving between the group's own accounts (paying the credit card, topping up savings).

Such transfers are not spending. Whether a transaction counts as one comes from three inputs:
1. a person's choice (Transaction.transfer_user): always wins, in both directions
2. a matched pair: money out of one of the group's accounts and the same amount into another
3. what the bank file said (Transaction.source_transfer), e.g. NAB's "CREDIT CARD PAYMENT"

Matching is deliberately strict. A false match hides real spending (rent that happens to equal a
partner's top-up), which is worse than a missed one, and a missed one is easy to mark by hand.
"""

import re
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.categories import Categoriser
from app.core.models import Account, Transaction

PAIR_WINDOW_DAYS = 3
# Bank transaction types that can be one leg of a transfer. Rows without a type (most CSV layouts) also qualify.
_TRANSFER_HINTS = ("TRANSFER", "PAYMENT")
# How a payment into a credit card reads, across banks.
_CARD_PAYMENT = re.compile(r"payment|thank\s*you|bpay|autopay|direct\s*debit|transfer", re.IGNORECASE)


def is_transfer(t: Transaction) -> bool:
    if t.transfer_user is not None:
        return t.transfer_user
    return t.source_transfer or t.transfer_pair_id is not None


def recategorise(t: Transaction, categoriser: Categoriser) -> bool:
    """Recomputes a category that wasn't chosen by hand. Returns True if it changed."""
    if t.category_source == "user":
        return False
    category_id, source = categoriser.resolve(
        description=t.description,
        merchant=t.merchant,
        bank_category=t.bank_category,
        is_transfer=t.is_internal_transfer,
    )
    changed = (category_id, source) != (t.category_id, t.category_source)
    t.category_id, t.category_source = category_id, source
    return changed


def refresh(t: Transaction, categoriser: Categoriser) -> None:
    """Brings is_internal_transfer (and an automatic category) in line with the inputs."""
    t.is_internal_transfer = is_transfer(t)
    recategorise(t, categoriser)


def unpair(db: Session, t: Transaction, categoriser: Categoriser) -> list[Transaction]:
    """Splits t from its partner. Returns the partner legs, already refreshed."""
    if t.transfer_pair_id is None:
        return []
    partners = list(
        db.scalars(
            select(Transaction).where(
                Transaction.group_id == t.group_id,
                Transaction.transfer_pair_id == t.transfer_pair_id,
                Transaction.id != t.id,
            )
        )
    )
    t.transfer_pair_id = None
    refresh(t, categoriser)
    for p in partners:
        p.transfer_pair_id = None
        refresh(p, categoriser)
    return partners


def _digits_of(ref: str) -> str | None:
    digits = re.sub(r"\D", "", ref)
    return digits[-4:] if len(digits) >= 4 else None


def _mentions(description: str, account: Account) -> bool:
    """True if a description names the other account, e.g. "PAYMENT TO CARD 1111" for "Card ending 1111"."""
    tail = _digits_of(account.external_ref)
    return bool(tail and re.search(rf"(?<!\d){tail}(?!\d)", description))


def _leg(t: Transaction) -> bool:
    if t.source_transfer or t.transfer_user:
        return True
    return not t.bank_type or any(h in t.bank_type.upper() for h in _TRANSFER_HINTS)


def _evidence(out: Transaction, inc: Transaction, accounts: dict[uuid.UUID, Account]) -> bool:
    """Something beyond a matching amount says these two belong together."""
    if out.source_transfer or inc.source_transfer or out.transfer_user or inc.transfer_user:
        return True
    into = accounts[inc.account_id]
    if into.kind == "credit_card" and _CARD_PAYMENT.search(inc.description):
        return True
    return _mentions(out.description, into) or _mentions(inc.description, accounts[out.account_id])


def pair_transfers(db: Session, group_id: uuid.UUID, categoriser: Categoriser | None = None) -> int:
    """Pairs money leaving one of the group's accounts with the same amount arriving in another.

    A pair needs the same amount, different accounts, at most PAIR_WINDOW_DAYS apart, both legs
    shaped like a transfer, and evidence: the bank marked a leg as a transfer, a person did, the
    money went into a credit card as a payment, or one description names the other account.
    Rows a person marked "not a transfer" never take part. The closest date wins.
    """
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.group_id == group_id))}
    candidates = [
        t
        for t in db.scalars(
            select(Transaction)
            .where(
                Transaction.group_id == group_id,
                Transaction.transfer_pair_id.is_(None),
                Transaction.is_pending.is_(False),
            )
            .order_by(Transaction.posted_date, Transaction.created_at)
        )
        if t.transfer_user is not False and _leg(t)
    ]
    incoming: dict = defaultdict(list)
    for t in candidates:
        if t.amount > 0:
            incoming[t.amount].append(t)
    categoriser = categoriser or Categoriser(db, group_id)
    paired = 0
    for out in candidates:
        if out.amount >= 0 or out.transfer_pair_id is not None:
            continue
        options = [
            inc
            for inc in incoming.get(-out.amount, [])
            if inc.transfer_pair_id is None
            and inc.account_id != out.account_id
            and abs((inc.posted_date - out.posted_date).days) <= PAIR_WINDOW_DAYS
            and _evidence(out, inc, accounts)
        ]
        if not options:
            continue
        inc = min(options, key=lambda i: abs((i.posted_date - out.posted_date).days))
        pair_id = uuid.uuid4()
        for leg in (out, inc):
            leg.transfer_pair_id = pair_id
            refresh(leg, categoriser)
        paired += 1
    db.flush()
    return paired


def delete_transactions(db: Session, group_id: uuid.UUID, txs: list[Transaction]) -> int:
    """Deletes transactions, first splitting any transfer pair whose other leg stays behind."""
    if not txs:
        return 0
    categoriser = Categoriser(db, group_id)
    doomed = {t.id for t in txs}
    for t in txs:
        if t.transfer_pair_id is not None:
            for p in unpair(db, t, categoriser):
                if p.id in doomed:
                    p.transfer_pair_id = None
    for t in txs:
        db.delete(t)
    db.flush()
    return len(txs)
