"""Decides a transaction's category from a chain of matchers.

Order (the first matcher with an answer wins):
1. transfer      money between the group's own accounts -> "Internal transfers"
2. rule          the group's own rules, lowest priority number first            (source "rule")
3. learned       a payee someone in the group has categorised by hand before    (source "auto")
4. bank          the bank's category, when it says what the money was for       (source "bank")
5. keyword       built-in words and well-known payees, e.g. "rent", "Bunnings"   (source "auto")
6. similar       a payee that looks like one already categorised (fuzzy match)  (source "auto")
7. fallback      money in the bank called "Transfers in" -> "Other income"      (source "bank")
otherwise        "Uncategorised"

A category a person chose by hand (source "user") is never recomputed; callers skip those.
Each matcher is a small class with one method, so new ones (e.g. the AI coach, source "coach")
slot into the chain without touching the others.
"""

import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.categories import TRANSFER_CATEGORY, UNCATEGORISED, visible_categories
from app.core.categorisation.library import BANK_ALIASES, FALLBACK_IN, KEYWORDS, UNINFORMATIVE
from app.core.categorisation.text import fold, payee_key, similar
from app.core.models import Category, CategoryRule, Transaction

SIMILAR_THRESHOLD = 0.86


@dataclass(frozen=True)
class Facts:
    """What the matchers may look at."""

    description: str
    merchant: str | None
    bank_category: str | None
    amount: Decimal | None
    is_transfer: bool

    @property
    def text(self) -> str:
        return f"{self.merchant or ''} {self.description}"

    @property
    def direction(self) -> str:
        if self.amount is None:
            return "any"
        return "in" if self.amount > 0 else "out"


@dataclass(frozen=True)
class Decision:
    category_id: uuid.UUID | None
    source: str  # "bank" | "rule" | "auto" (and later "coach")
    reason: str | None = None  # short, for people: why this category


class Matcher(Protocol):
    def match(self, f: Facts) -> Decision | None: ...


class _Context:
    """Everything the matchers need for one group, loaded once per import or re-run."""

    def __init__(self, db: Session, group_id: uuid.UUID):
        self.group_id = group_id
        cats = visible_categories(db, group_id)
        self.by_id: dict[uuid.UUID, Category] = {c.id: c for c in cats}
        self.by_name: dict[str, Category] = {c.name.lower(): c for c in cats}
        self.transfer = self.by_name.get(TRANSFER_CATEGORY.lower())
        self.uncategorised = self.by_name.get(UNCATEGORISED.lower())
        # Payee memory, built from the group's own transactions.
        #   chosen: categories people picked by hand
        #   known:  everything with a real category from a person or the bank (not from guesses)
        self.chosen: dict[str, Counter] = defaultdict(Counter)
        self.known: dict[str, Counter] = defaultdict(Counter)
        unc_id = self.uncategorised.id if self.uncategorised else None
        tid = self.transfer.id if self.transfer else None
        rows = db.execute(
            select(
                Transaction.description,
                Transaction.merchant,
                Transaction.bank_category,
                Transaction.category_id,
                Transaction.category_source,
            ).where(
                Transaction.group_id == group_id,
                Transaction.is_internal_transfer.is_(False),
                Transaction.category_id.is_not(None),
                Transaction.category_source.in_(("user", "bank")),
            )
        )
        for desc, merch, bank_cat, cid, src in rows:
            if cid in (unc_id, tid) or cid not in self.by_id:
                continue
            # A "bank" row only counts when the bank's own category says so (not a stale earlier result).
            if src == "bank" and self.bank_category(bank_cat) != cid:
                continue
            key = payee_key(desc, merch)
            if len(key) < 3:
                continue
            if src == "user":
                self.chosen[key][cid] += 1
            self.known[key][cid] += 1

    def bank_category(self, bank_name: str | None) -> uuid.UUID | None:
        name = (bank_name or "").strip().lower()
        if name in UNINFORMATIVE:
            return None
        c = self.by_name.get(name) or self.by_name.get(BANK_ALIASES.get(name, "").lower())
        return c.id if c else None

    def name(self, cid: uuid.UUID) -> str:
        c = self.by_id.get(cid)
        return c.name if c else "?"


def _best(counter: Counter) -> uuid.UUID:
    return counter.most_common(1)[0][0]


class TransferMatcher:
    def __init__(self, ctx: _Context):
        self.ctx = ctx

    def match(self, f: Facts) -> Decision | None:
        if f.is_transfer and self.ctx.transfer is not None:
            return Decision(self.ctx.transfer.id, "bank", "Between your own accounts")
        return None


class RuleMatcher:
    def __init__(self, db: Session, group_id: uuid.UUID):
        self.rules: list[tuple[CategoryRule, re.Pattern | None]] = []
        for r in db.scalars(
            select(CategoryRule)
            .where(CategoryRule.group_id == group_id)
            .order_by(CategoryRule.priority, CategoryRule.created_at)
        ):
            rx = None
            if r.is_regex:
                try:
                    rx = re.compile(r.pattern, re.IGNORECASE)
                except re.error:
                    continue  # an invalid pattern is skipped, never fatal
            self.rules.append((r, rx))

    def match(self, f: Facts) -> Decision | None:
        text = f.text
        low = text.lower()
        for r, rx in self.rules:
            if rx.search(text) if rx is not None else r.pattern.lower() in low:
                return Decision(r.category_id, "rule", f'Your rule "{r.pattern}"')
        return None


class LearnedPayeeMatcher:
    """Same payee as one someone in the group categorised by hand."""

    def __init__(self, ctx: _Context):
        self.ctx = ctx

    def match(self, f: Facts) -> Decision | None:
        key = payee_key(f.description, f.merchant)
        hit = self.ctx.chosen.get(key)
        if hit:
            return Decision(_best(hit), "auto", f'You put "{key}" here before')
        return None


class BankCategoryMatcher:
    def __init__(self, ctx: _Context):
        self.ctx = ctx

    def match(self, f: Facts) -> Decision | None:
        cid = self.ctx.bank_category(f.bank_category)
        return Decision(cid, "bank", None) if cid is not None else None


class KeywordMatcher:
    def __init__(self, ctx: _Context):
        self.ctx = ctx

    def match(self, f: Facts) -> Decision | None:
        text = fold(f.text)
        for kw in KEYWORDS:
            if kw.direction != "any" and f.direction not in (kw.direction, "any"):
                continue
            m = kw.pattern.search(text)
            if m is None:
                continue
            c = self.ctx.by_name.get(kw.category.lower())
            if c is not None:
                return Decision(c.id, "auto", f'"{m.group(0)}" in the text')
        return None


class SimilarPayeeMatcher:
    """A payee that looks like one with a known category, e.g. the same shop on a different card."""

    def __init__(self, ctx: _Context):
        self.ctx = ctx
        self.keys = list(ctx.known.keys())

    def match(self, f: Facts) -> Decision | None:
        key = payee_key(f.description, f.merchant)
        if len(key) < 4:
            return None
        hit = self.ctx.known.get(key)
        if hit:
            return Decision(_best(hit), "auto", f'Same payee as earlier "{key}" transactions')
        best, score = None, 0.0
        for k in self.keys:
            s = similar(key, k)
            if s > score:
                best, score = k, s
        if best is not None and score >= SIMILAR_THRESHOLD:
            return Decision(_best(self.ctx.known[best]), "auto", f'Looks like "{best}"')
        return None


class FallbackMatcher:
    def __init__(self, ctx: _Context):
        self.ctx = ctx

    def match(self, f: Facts) -> Decision | None:
        name = (f.bank_category or "").strip().lower()
        if f.direction == "in" and name in FALLBACK_IN:
            c = self.ctx.by_name.get(FALLBACK_IN[name].lower())
            if c is not None:
                return Decision(c.id, "bank", None)
        return None


class Categoriser:
    """Resolves categories for one group. Build once per import or re-categorisation run."""

    def __init__(self, db: Session, group_id: uuid.UUID):
        self.ctx = _Context(db, group_id)
        self.by_name = self.ctx.by_name
        self.transfer = self.ctx.transfer
        self.uncategorised = self.ctx.uncategorised
        self.matchers: list[Matcher] = [
            TransferMatcher(self.ctx),
            RuleMatcher(db, group_id),
            LearnedPayeeMatcher(self.ctx),
            BankCategoryMatcher(self.ctx),
            KeywordMatcher(self.ctx),
            SimilarPayeeMatcher(self.ctx),
            FallbackMatcher(self.ctx),
        ]

    def decide(
        self,
        *,
        description: str,
        merchant: str | None,
        bank_category: str | None,
        is_transfer: bool,
        amount: Decimal | None = None,
    ) -> Decision:
        f = Facts(description or "", merchant, bank_category, amount, is_transfer)
        for m in self.matchers:
            d = m.match(f)
            if d is not None:
                return d
        return Decision(self.uncategorised.id if self.uncategorised else None, "bank", None)

    def resolve(self, **kwargs) -> tuple[uuid.UUID | None, str]:
        d = self.decide(**kwargs)
        return d.category_id, d.source

    def learn(self, description: str, merchant: str | None, category_id: uuid.UUID) -> str:
        """Remembers a hand-picked category for this payee from now on. Returns the payee key."""
        key = payee_key(description, merchant)
        if len(key) >= 3:
            self.ctx.chosen[key] = Counter({category_id: 1})
            self.ctx.known[key][category_id] += 1
        return key
