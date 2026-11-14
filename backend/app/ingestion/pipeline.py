"""Turns a connector's ParsedRows into stored transactions.

Steps, in one database transaction:
1. find or create the group's accounts the file mentions
2. drop pending rows the new file supersedes (pending rows are a snapshot, not history)
3. skip rows already imported (by fingerprint), store the rest with a category
4. pair internal transfers between the group's own accounts so they are not counted as spending
"""

import hashlib
import uuid
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.categories import Categoriser
from app.core.models import Account, ImportBatch, Transaction
from app.core.transfers import pair_transfers
from app.ingestion.connectors.base import Connector, ParsedRow


@dataclass
class ImportOutcome:
    batch: ImportBatch
    accounts_created: list[str] = field(default_factory=list)
    accounts_in_file: list[str] = field(default_factory=list)
    transfers_paired: int = 0


def fingerprint(row: ParsedRow, occurrence: int) -> str:
    """Identifies a row across overlapping exports.

    The running balance is left out on purpose: banks can recompute it when pending items settle.
    Identical rows on the same day (two coffees at the same price) are told apart by their
    position among the identical rows in the file.
    """
    key = "|".join(
        [
            row.account_ref.strip().lower(),
            row.posted_date.isoformat(),
            str(row.amount),
            " ".join(row.description.split()).lower(),
            "p" if row.is_pending else "s",
            str(occurrence),
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def _accounts(db: Session, group_id: uuid.UUID, connector: Connector, refs: set[str], outcome: ImportOutcome):
    found = {
        a.external_ref: a
        for a in db.scalars(
            select(Account).where(
                Account.group_id == group_id,
                Account.institution == connector.institution,
                Account.external_ref.in_(refs),
            )
        )
    }
    for ref in sorted(refs - found.keys()):
        a = Account(
            group_id=group_id,
            name=f"{connector.institution} {ref}",
            kind=connector.account_kind(ref),
            institution=connector.institution,
            external_ref=ref,
        )
        db.add(a)
        found[ref] = a
        outcome.accounts_created.append(a.name)
    db.flush()
    return found


def import_rows(
    db: Session,
    *,
    group_id: uuid.UUID,
    user_id: uuid.UUID | None,
    connector: Connector,
    rows: list[ParsedRow],
    filename: str | None = None,
) -> ImportOutcome:
    batch = ImportBatch(
        group_id=group_id,
        source=connector.source,
        filename=filename,
        imported_by=user_id,
        rows_total=0,
        rows_new=0,
        rows_duplicate=0,
        rows_pending_replaced=0,
    )
    db.add(batch)
    outcome = ImportOutcome(batch=batch)
    # Flushes the batch too, so batch.id is set from here on.
    accounts = _accounts(db, group_id, connector, {r.account_ref for r in rows}, outcome)
    outcome.accounts_in_file = sorted(a.name for a in accounts.values())

    # 2. Pending rows: the new file is the current truth from its earliest date onwards.
    earliest: dict[str, object] = {}
    for r in rows:
        if r.account_ref not in earliest or r.posted_date < earliest[r.account_ref]:
            earliest[r.account_ref] = r.posted_date
    for ref, first in earliest.items():
        res = db.execute(
            delete(Transaction).where(
                Transaction.account_id == accounts[ref].id,
                Transaction.is_pending.is_(True),
                Transaction.posted_date >= first,
            )
        )
        batch.rows_pending_replaced += res.rowcount or 0

    # 3. New rows.
    account_ids = [a.id for a in accounts.values()]
    existing = set(db.scalars(select(Transaction.fingerprint).where(Transaction.account_id.in_(account_ids))).all())
    categoriser = Categoriser(db, group_id)
    seen: Counter = Counter()
    new: list[Transaction] = []
    for r in rows:
        ident = (r.account_ref, r.posted_date, r.amount, " ".join(r.description.split()).lower(), r.is_pending)
        fp = fingerprint(r, seen[ident])
        seen[ident] += 1
        batch.rows_total += 1
        if fp in existing:
            batch.rows_duplicate += 1
            continue
        existing.add(fp)
        is_transfer = connector.is_internal_transfer(r)
        category_id, source = categoriser.resolve(
            description=r.description, merchant=r.merchant, bank_category=r.bank_category, is_transfer=is_transfer
        )
        t = Transaction(
            group_id=group_id,
            account_id=accounts[r.account_ref].id,
            import_batch_id=batch.id,
            posted_date=r.posted_date,
            amount=r.amount,
            currency=accounts[r.account_ref].currency,
            description=r.description,
            merchant=r.merchant,
            bank_type=r.bank_type,
            bank_category=r.bank_category,
            balance_after=r.balance_after,
            is_pending=r.is_pending,
            category_id=category_id,
            category_source=source,
            is_internal_transfer=is_transfer,
            source_transfer=is_transfer,
            fingerprint=fp,
            raw=r.raw,
        )
        db.add(t)
        new.append(t)
    batch.rows_new = len(new)
    db.flush()

    # 4. Transfers between the group's own accounts.
    outcome.transfers_paired = pair_transfers(db, group_id, categoriser)
    audit.log(
        db,
        "import.completed",
        user_id=user_id,
        group_id=group_id,
        source=connector.source,
        rows_new=batch.rows_new,
        rows_duplicate=batch.rows_duplicate,
    )
    return outcome


__all__ = ["fingerprint", "import_rows", "pair_transfers"]
