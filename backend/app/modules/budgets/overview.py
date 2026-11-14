"""The spending overview. Every figure the web app shows is computed here, never in the browser
(and later never by the AI coach): one place to test, the same numbers on web and mobile.

What counts as spending: money out of the group's accounts, minus refunds (money in that sits in a
spending category), excluding transfers between the group's own accounts and anything in an income
or transfer category.
"""

import calendar
import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.categories import visible_categories
from app.core.deps import GroupAccess, group_access
from app.core.models import Account, Transaction
from app.db import get_db
from app.modules.budgets.routes import load_budget

router = APIRouter(prefix="/api/groups/{group_id}/overview", tags=["overview"])

ZERO = Decimal("0")
AVG_MONTH_DAYS = Decimal("30.44")
EATING_OUT = {"restaurants & takeaway", "cafe & coffee"}
FEES = {"fees", "loans"}
RECURRING_CATEGORIES = {"subscriptions", "phone & internet", "insurance", "utilities"}
_PREFIX = re.compile(r"^(SQ \*|SP |SMP\*|ZLR\*|KPAY\*|COM\*|DD \*|PAYPAL \*|LS )", re.IGNORECASE)
_PLACE = re.compile(r"\s+(\d{3,}|AUS?|AU|NSW|VIC|QLD|MELBOURNE|SYDNEY)\b.*$", re.IGNORECASE)


def merchant_name(t: Transaction) -> str:
    """A tidy name to group purchases by: the bank's merchant name, else a cleaned description."""
    if t.merchant and t.merchant.lower() not in ("square", "compasspay", "paypal"):
        return re.sub(r"\s*\(.*?\)\s*", " ", t.merchant).strip()
    d = _PREFIX.sub("", t.description.strip())
    d = _PLACE.sub("", d)
    words = re.sub(r"[^A-Za-z&' ]", " ", d).split()[:3]
    return " ".join(words).title() or t.description[:30]


class Period(BaseModel):
    key: str
    label: str
    start: date
    end: date
    days: int
    data_from: date | None
    data_to: date | None
    days_with_data: int
    elapsed: float  # share of the period that has passed (1.0 for a finished month)


class PostLine(BaseModel):
    id: str  # post id, or "none" for spending not in any budget post
    name: str
    heading: str | None
    color: int  # 0 = neutral (not in a budget)
    spent: Decimal
    count: int
    budget: Decimal | None
    pace: Decimal | None  # where spending "should" be by now, for the current month
    category_ids: list[uuid.UUID]


class HeadingLine(BaseModel):
    id: str
    name: str
    spent: Decimal
    budget: Decimal | None
    over: int


class CategoryLine(BaseModel):
    id: uuid.UUID | None
    name: str
    spent: Decimal
    count: int
    post_id: str


class AccountLine(BaseModel):
    id: uuid.UUID
    name: str
    spent: Decimal
    count: int
    top_post: str | None


class MerchantLine(BaseModel):
    name: str
    spent: Decimal
    count: int


class RecurringLine(BaseModel):
    name: str
    amount: Decimal
    count: int
    last_date: date


class Day(BaseModel):
    date: date
    total: Decimal
    by_post: dict[str, Decimal]


class Insights(BaseModel):
    eating_out_total: Decimal
    eating_out_count: int
    eating_out_per_week: Decimal
    most_frequent: MerchantLine | None
    biggest_day: Day | None
    biggest_day_merchants: list[str]
    fees_total: Decimal
    fees_count: int


class Overview(BaseModel):
    period: Period
    months: list[dict]
    total: Decimal
    purchases: int
    refunds: Decimal
    per_day: Decimal
    biggest_purchase: MerchantLine | None
    days: list[Day]
    posts: list[PostLine]
    headings: list[HeadingLine]
    categories: list[CategoryLine]
    accounts: list[AccountLine]
    merchants: list[MerchantLine]
    recurring: list[RecurringLine]
    insights: Insights
    budgets_set: int
    budgets_over: int
    budget_total: Decimal
    budget_spent: Decimal


def _month_bounds(key: str) -> tuple[date, date]:
    y, m = (int(x) for x in key.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def _label(start: date) -> str:
    return start.strftime("%B %Y")


@router.get("", response_model=Overview)
def overview(
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
    period: str | None = Query(default=None, pattern=r"^(\d{4}-\d{2}|all)$"),
    account_id: uuid.UUID | None = None,
    today: date | None = None,  # for tests; defaults to the real date
):
    gid = access.group.id
    today = today or date.today()
    cats = {c.id: c for c in visible_categories(db, gid)}
    accounts = {a.id: a for a in db.scalars(select(Account).where(Account.group_id == gid))}
    if account_id and account_id not in accounts:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found.")

    def counts(t: Transaction) -> bool:
        if t.is_internal_transfer:
            return False
        c = cats.get(t.category_id) if t.category_id else None
        if t.amount > 0:
            # Money in only lowers spending when it is a refund in a spending category; salary and
            # other uncategorised money in is income, not negative spending.
            return c is not None and c.kind == "expense" and c.name != "Uncategorised"
        return c is None or c.kind == "expense"

    conds = [Transaction.group_id == gid]
    if account_id:
        conds.append(Transaction.account_id == account_id)
    all_tx = [t for t in db.scalars(select(Transaction).where(*conds)) if counts(t)]

    months = sorted({t.posted_date.strftime("%Y-%m") for t in all_tx}, reverse=True)
    key = period or (months[0] if months else today.strftime("%Y-%m"))
    if key == "all":
        start = min((t.posted_date for t in all_tx), default=today)
        end = max((t.posted_date for t in all_tx), default=today)
        label = "All data"
    else:
        start, end = _month_bounds(key)
        label = _label(start)
    txs = sorted((t for t in all_tx if start <= t.posted_date <= end), key=lambda t: t.posted_date)
    data_from = min((t.posted_date for t in txs), default=None)
    data_to = max((t.posted_date for t in txs), default=None)
    days_in_period = (end - start).days + 1
    if key != "all" and start <= today <= end:
        elapsed = ((today - start).days + 1) / days_in_period
        last_day = today
    else:
        elapsed = 1.0
        last_day = end if key != "all" else (data_to or end)

    # Budget structure: category -> post.
    budget = load_budget(db, gid)
    post_of: dict[uuid.UUID, str] = {}
    post_meta: dict[str, dict] = {}
    for h in budget.headings:
        for p in h.posts:
            pid = str(p.id)
            post_meta[pid] = {"name": p.name, "heading": h.name, "heading_id": str(h.id), "color": p.color, "p": p}
            for cid in p.category_ids:
                post_of[cid] = pid

    def post_for(t: Transaction) -> str:
        return post_of.get(t.category_id, "none") if t.category_id else "none"

    spend = {t.id: -t.amount for t in txs}
    total = sum(spend.values(), ZERO)
    refunds = sum((-v for v in spend.values() if v < 0), ZERO)
    purchases = sum(1 for v in spend.values() if v > 0)

    by_post: dict[str, Decimal] = defaultdict(lambda: ZERO)
    count_post: dict[str, int] = defaultdict(int)
    by_cat: dict[uuid.UUID | None, Decimal] = defaultdict(lambda: ZERO)
    count_cat: dict[uuid.UUID | None, int] = defaultdict(int)
    by_acc: dict[uuid.UUID, Decimal] = defaultdict(lambda: ZERO)
    count_acc: dict[uuid.UUID, int] = defaultdict(int)
    acc_post: dict[uuid.UUID, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    by_merchant: dict[str, Decimal] = defaultdict(lambda: ZERO)
    count_merchant: dict[str, int] = defaultdict(int)
    by_day: dict[date, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: ZERO))
    for t in txs:
        v, pid = spend[t.id], post_for(t)
        by_post[pid] += v
        by_cat[t.category_id] += v
        by_acc[t.account_id] += v
        acc_post[t.account_id][pid] += v
        by_day[t.posted_date][pid] += v
        if v > 0:
            count_post[pid] += 1
            count_cat[t.category_id] += 1
            count_acc[t.account_id] += 1
            name = merchant_name(t)
            count_merchant[name] += 1
        by_merchant[merchant_name(t)] += v

    # Budget amounts scale to the period: a month is one monthly amount, "all data" is pro rata.
    scale = Decimal("1") if key != "all" else (Decimal(days_in_period) / AVG_MONTH_DAYS)
    posts_out: list[PostLine] = []
    for pid, meta in post_meta.items():
        p = meta["p"]
        b = (p.monthly_amount * scale).quantize(Decimal("0.01")) if p.monthly_amount is not None else None
        pace = (b * Decimal(str(elapsed))).quantize(Decimal("0.01")) if b is not None and elapsed < 1 else None
        posts_out.append(
            PostLine(
                id=pid,
                name=meta["name"],
                heading=meta["heading"],
                color=meta["color"],
                spent=by_post.get(pid, ZERO),
                count=count_post.get(pid, 0),
                budget=b,
                pace=pace,
                category_ids=p.category_ids,
            )
        )
    unbudgeted_cats = sorted({t.category_id for t in txs if post_for(t) == "none" and t.category_id}, key=str)
    if by_post.get("none") or not post_meta:
        posts_out.append(
            PostLine(
                id="none",
                name="Not in a budget",
                heading=None,
                color=0,
                spent=by_post.get("none", ZERO),
                count=count_post.get("none", 0),
                budget=None,
                pace=None,
                category_ids=unbudgeted_cats,
            )
        )

    headings_out = []
    for h in budget.headings:
        lines = [p for p in posts_out if p.heading == h.name and p.id in {str(x.id) for x in h.posts}]
        budgets = [p.budget for p in lines if p.budget is not None]
        headings_out.append(
            HeadingLine(
                id=str(h.id),
                name=h.name,
                spent=sum((p.spent for p in lines), ZERO),
                budget=sum(budgets, ZERO) if budgets else None,
                over=sum(1 for p in lines if p.budget is not None and p.spent > p.budget),
            )
        )

    with_budget = [p for p in posts_out if p.budget is not None]
    days_list = []
    if data_from:
        d = start if key != "all" else data_from
        while d <= last_day:
            parts = by_day.get(d, {})
            days_list.append(
                Day(date=d, total=sum(parts.values(), ZERO), by_post={k: v for k, v in parts.items() if v})
            )
            d += timedelta(days=1)
    days_with_data = (data_to - data_from).days + 1 if data_from and data_to else 0

    # Insights.
    eat = [t for t in txs if t.category_id in cats and cats[t.category_id].name.lower() in EATING_OUT]
    eat_total = sum((spend[t.id] for t in eat), ZERO)
    weeks = Decimal(max(days_with_data, 1)) / Decimal(7)
    fees = [
        t
        for t in txs
        if (t.category_id in cats and cats[t.category_id].name.lower() in FEES)
        or any(w in (t.bank_type or "").upper() for w in ("FEE", "INTEREST"))
    ]
    freq = max(count_merchant.items(), key=lambda kv: (kv[1], by_merchant[kv[0]]), default=None)
    biggest_day = max(days_list, key=lambda d: d.total, default=None)
    big_merchants: list[str] = []
    if biggest_day and biggest_day.total > 0:
        on_day = defaultdict(lambda: ZERO)
        for t in txs:
            if t.posted_date == biggest_day.date:
                on_day[merchant_name(t)] += spend[t.id]
        big_merchants = [m for m, _ in sorted(on_day.items(), key=lambda kv: -kv[1])[:2]]
    biggest = max(txs, key=lambda t: spend[t.id], default=None)

    return Overview(
        period=Period(
            key=key,
            label=label,
            start=start,
            end=end,
            days=days_in_period,
            data_from=data_from,
            data_to=data_to,
            days_with_data=days_with_data,
            elapsed=elapsed,
        ),
        months=[{"key": m, "label": _label(_month_bounds(m)[0])} for m in months],
        total=total,
        purchases=purchases,
        refunds=refunds,
        per_day=(total / Decimal(max(days_with_data, 1))).quantize(Decimal("0.01")),
        biggest_purchase=MerchantLine(name=merchant_name(biggest), spent=spend[biggest.id], count=1)
        if biggest is not None and spend[biggest.id] > 0
        else None,
        days=days_list,
        posts=sorted(posts_out, key=lambda p: -p.spent),
        headings=headings_out,
        categories=sorted(
            (
                CategoryLine(
                    id=cid,
                    name=cats[cid].name if cid in cats else "Uncategorised",
                    spent=v,
                    count=count_cat.get(cid, 0),
                    post_id=post_of.get(cid, "none") if cid else "none",
                )
                for cid, v in by_cat.items()
            ),
            key=lambda c: -c.spent,
        ),
        accounts=sorted(
            (
                AccountLine(
                    id=aid,
                    name=accounts[aid].name,
                    spent=v,
                    count=count_acc.get(aid, 0),
                    top_post=max(acc_post[aid].items(), key=lambda kv: kv[1])[0] if acc_post[aid] else None,
                )
                for aid, v in by_acc.items()
            ),
            key=lambda a: -a.spent,
        ),
        merchants=[
            MerchantLine(name=n, spent=v, count=count_merchant.get(n, 0))
            for n, v in sorted(by_merchant.items(), key=lambda kv: -kv[1])[:8]
            if v > 0
        ],
        recurring=_recurring(all_tx, cats, end),
        insights=Insights(
            eating_out_total=eat_total,
            eating_out_count=sum(1 for t in eat if spend[t.id] > 0),
            eating_out_per_week=(eat_total / weeks).quantize(Decimal("0.01")) if eat else ZERO,
            most_frequent=MerchantLine(name=freq[0], spent=by_merchant[freq[0]], count=freq[1]) if freq else None,
            biggest_day=biggest_day if biggest_day and biggest_day.total > 0 else None,
            biggest_day_merchants=big_merchants,
            fees_total=sum((spend[t.id] for t in fees), ZERO),
            fees_count=len(fees),
        ),
        budgets_set=len(with_budget),
        budgets_over=sum(1 for p in with_budget if p.spent > p.budget),
        budget_total=sum((p.budget for p in with_budget), ZERO),
        budget_spent=sum((p.spent for p in with_budget), ZERO),
    )


def _recurring(txs: list[Transaction], cats: dict, until: date) -> list[RecurringLine]:
    """Charges that repeat: anything in a bills category, or the same merchant charging almost the
    same amount at least 25 days apart and no more often than about monthly (so a favourite café
    doesn't count). Looks at all data up to the end of the period."""
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for t in txs:
        if t.amount < 0 and t.posted_date <= until:
            groups[merchant_name(t)].append(t)
    out = []
    for name, items in groups.items():
        items.sort(key=lambda t: t.posted_date)
        last = items[-1]
        amt = -last.amount
        is_bill = last.category_id in cats and cats[last.category_id].name.lower() in RECURRING_CATEGORIES
        similar = [t for t in items if abs(-t.amount - amt) <= max(amt * Decimal("0.02"), Decimal("0.5"))]
        spread = (similar[-1].posted_date - similar[0].posted_date).days
        regular = len(similar) >= 2 and spread >= 25 and len(similar) <= spread / 25 + 1
        if is_bill or (regular and len(items) <= spread / 20 + 2):
            out.append(RecurringLine(name=name, amount=amt, count=len(similar), last_date=last.posted_date))
    return sorted(out, key=lambda r: -r.amount)[:10]
