"""Accounts, categories, category rules and transactions. Everything is scoped to one group."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.categories import Categoriser, get_or_create_category, validate_regex, visible_categories
from app.core.deps import GroupAccess, group_access, owner_access
from app.core.models import Account, Category, CategoryRule, Membership, Transaction
from app.core.schemas import (
    AccountOut,
    AccountPatch,
    ApplyRulesResult,
    CategoryIn,
    CategoryOut,
    RuleIn,
    RuleOut,
    TransactionOut,
    TransactionPage,
    TransactionPatch,
)
from app.core.transfers import delete_transactions, pair_transfers, recategorise, refresh, unpair
from app.db import get_db

router = APIRouter(prefix="/api/groups/{group_id}", tags=["finance"])


# ---- accounts


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    return db.scalars(select(Account).where(Account.group_id == access.group.id).order_by(Account.name)).all()


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID,
    body: AccountPatch,
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
):
    account = _get(db, Account, account_id, access, "Account")
    if body.name is not None:
        account.name = body.name.strip()
    if body.clear_owner:
        account.owner_user_id = None
    elif body.owner_user_id is not None:
        is_member = db.scalar(
            select(Membership).where(Membership.group_id == access.group.id, Membership.user_id == body.owner_user_id)
        )
        if is_member is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The owner must be a member of the group.")
        account.owner_user_id = body.owner_user_id
    audit.log(db, "account.updated", user_id=access.user.id, group_id=access.group.id, account=str(account.id))
    db.commit()
    return account


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: uuid.UUID, access: GroupAccess = Depends(owner_access), db: Session = Depends(get_db)):
    """Deletes an account and all its transactions. Only the group's owners can do this."""
    account = _get(db, Account, account_id, access, "Account")
    txs = list(db.scalars(select(Transaction).where(Transaction.account_id == account.id)))
    removed = delete_transactions(db, access.group.id, txs)
    db.delete(account)
    audit.log(
        db, "account.deleted", user_id=access.user.id, group_id=access.group.id, name=account.name, removed=removed
    )
    db.commit()


# ---- categories


@router.get("/categories", response_model=list[CategoryOut])
def list_categories(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    return visible_categories(db, access.group.id)


@router.post("/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(body: CategoryIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    name = body.name.strip()
    if any(c.name.lower() == name.lower() for c in visible_categories(db, access.group.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "A category with this name already exists.")
    c = Category(group_id=access.group.id, name=name, kind=body.kind)
    db.add(c)
    audit.log(db, "category.created", user_id=access.user.id, group_id=access.group.id, name=name)
    db.commit()
    return c


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Only the group's own categories can be deleted. Its transactions go back to the rules and the bank."""
    c = db.get(Category, category_id)
    if c is None or c.group_id != access.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found, or it is built in.")
    affected = db.scalars(
        select(Transaction).where(Transaction.group_id == access.group.id, Transaction.category_id == c.id)
    ).all()
    db.execute(CategoryRule.__table__.delete().where(CategoryRule.category_id == c.id))
    db.delete(c)
    db.flush()
    categoriser = Categoriser(db, access.group.id)
    for t in affected:
        recategorise(t, categoriser)
    audit.log(db, "category.deleted", user_id=access.user.id, group_id=access.group.id, name=c.name)
    db.commit()


# ---- rules


@router.get("/rules", response_model=list[RuleOut])
def list_rules(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    return db.scalars(
        select(CategoryRule)
        .where(CategoryRule.group_id == access.group.id)
        .order_by(CategoryRule.priority, CategoryRule.created_at)
    ).all()


@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(body: RuleIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    _check_rule(db, access, body)
    r = CategoryRule(group_id=access.group.id, created_by=access.user.id, **body.model_dump())
    db.add(r)
    audit.log(db, "rule.created", user_id=access.user.id, group_id=access.group.id, pattern=body.pattern)
    db.commit()
    return r


@router.put("/rules/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: uuid.UUID, body: RuleIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)
):
    r = _get(db, CategoryRule, rule_id, access, "Rule")
    _check_rule(db, access, body)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit.log(db, "rule.updated", user_id=access.user.id, group_id=access.group.id, pattern=body.pattern)
    db.commit()
    return r


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    r = _get(db, CategoryRule, rule_id, access, "Rule")
    db.delete(r)
    audit.log(db, "rule.deleted", user_id=access.user.id, group_id=access.group.id, pattern=r.pattern)
    db.commit()


class RuleImportItem(BaseModel):
    pattern: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    is_regex: bool = False
    priority: int = Field(default=100, ge=0, le=10000)


class RuleImportIn(BaseModel):
    rules: list[RuleImportItem] = Field(max_length=1000)


@router.post("/rules/import", response_model=ApplyRulesResult)
def import_rules(body: RuleImportIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Adds many rules at once, naming categories by name and creating any that are missing."""
    existing = {
        (r.pattern.lower(), r.is_regex)
        for r in db.scalars(select(CategoryRule).where(CategoryRule.group_id == access.group.id))
    }
    added = 0
    for item in body.rules:
        if item.is_regex and (problem := validate_regex(item.pattern)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'{item.pattern}': {problem}")
        if (item.pattern.lower(), item.is_regex) in existing:
            continue
        cat = get_or_create_category(db, access.group.id, item.category)
        db.add(
            CategoryRule(
                group_id=access.group.id,
                pattern=item.pattern,
                is_regex=item.is_regex,
                category_id=cat.id,
                priority=item.priority,
                created_by=access.user.id,
            )
        )
        existing.add((item.pattern.lower(), item.is_regex))
        added += 1
    audit.log(db, "rule.imported", user_id=access.user.id, group_id=access.group.id, added=added)
    db.commit()
    return ApplyRulesResult(updated=added)


@router.post("/rules/apply", response_model=ApplyRulesResult)
def apply_rules(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Re-runs the rules over every transaction whose category was not chosen by hand."""
    categoriser = Categoriser(db, access.group.id)
    updated = 0
    for t in db.scalars(
        select(Transaction).where(Transaction.group_id == access.group.id, Transaction.category_source != "user")
    ):
        if recategorise(t, categoriser):
            updated += 1
    audit.log(db, "rule.applied", user_id=access.user.id, group_id=access.group.id, updated=updated)
    db.commit()
    return ApplyRulesResult(updated=updated)


# ---- transactions


@router.get("/transactions", response_model=TransactionPage)
def list_transactions(
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
    account_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    category_ids: list[uuid.UUID] | None = Query(default=None, max_length=100),
    uncategorised: bool = False,
    include_transfers: bool = True,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    conds = [Transaction.group_id == access.group.id]
    if account_id:
        conds.append(Transaction.account_id == account_id)
    if category_id:
        conds.append(Transaction.category_id == category_id)
    if category_ids:
        conds.append(Transaction.category_id.in_(category_ids))
    if uncategorised:
        unc = select(Category.id).where(Category.group_id.is_(None), Category.name == "Uncategorised")
        conds.append(or_(Transaction.category_id.is_(None), Transaction.category_id.in_(unc)))
    if not include_transfers:
        conds.append(Transaction.is_internal_transfer.is_(False))
    if date_from:
        conds.append(Transaction.posted_date >= date_from)
    if date_to:
        conds.append(Transaction.posted_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Transaction.description.ilike(like), Transaction.merchant.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Transaction).where(*conds))
    items = db.scalars(
        select(Transaction)
        .where(*conds)
        .order_by(Transaction.posted_date.desc(), Transaction.created_at.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return TransactionPage(items=items, total=total or 0)


@router.patch("/transactions/{transaction_id}", response_model=TransactionOut)
def update_transaction(
    transaction_id: uuid.UUID,
    body: TransactionPatch,
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
):
    """Sets a category and/or whether it is a transfer between the group's own accounts.

    Only the fields sent are changed. null hands the choice back to the app (rules, the bank, matching).
    """
    t = _get(db, Transaction, transaction_id, access, "Transaction")
    sent = body.model_fields_set
    categoriser = Categoriser(db, access.group.id)
    if "category_id" in sent:
        if body.category_id is None:
            t.category_source = "bank"
            recategorise(t, categoriser)
        else:
            c = db.get(Category, body.category_id)
            if c is None or c.group_id not in (None, access.group.id):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown category.")
            t.category_id, t.category_source = c.id, "user"
        audit.log(
            db, "transaction.categorised", user_id=access.user.id, group_id=access.group.id, transaction=str(t.id)
        )
    if "is_transfer" in sent:
        t.transfer_user = body.is_transfer
        if body.is_transfer is False:
            unpair(db, t, categoriser)
        refresh(t, categoriser)
        if body.is_transfer is None:
            db.flush()
            pair_transfers(db, access.group.id, categoriser)
        audit.log(
            db,
            "transaction.transfer_set",
            user_id=access.user.id,
            group_id=access.group.id,
            transaction=str(t.id),
            is_transfer=body.is_transfer,
        )
    db.commit()
    db.refresh(t)
    return t


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)
):
    t = _get(db, Transaction, transaction_id, access, "Transaction")
    detail = {"transaction": str(t.id), "date": t.posted_date.isoformat(), "amount": str(t.amount)}
    delete_transactions(db, access.group.id, [t])
    audit.log(db, "transaction.deleted", user_id=access.user.id, group_id=access.group.id, **detail)
    db.commit()


# ---- helpers


def _get(db: Session, model, obj_id: uuid.UUID, access: GroupAccess, label: str):
    obj = db.get(model, obj_id)
    if obj is None or obj.group_id != access.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found.")
    return obj


def _check_rule(db: Session, access: GroupAccess, body: RuleIn) -> None:
    if body.is_regex and (problem := validate_regex(body.pattern)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    c = db.get(Category, body.category_id)
    if c is None or c.group_id not in (None, access.group.id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown category.")
