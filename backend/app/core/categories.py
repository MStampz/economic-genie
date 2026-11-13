"""Built-in categories and category resolution.

Order of precedence for a transaction's category:
1. a person chose it by hand (category_source = "user"): never changed automatically
2. the group's rules, lowest priority number first (source = "rule")
3. the bank's own category, matched by name (source = "bank")
Internal transfers always get the "Internal transfers" category.
"""

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.models import Category, CategoryRule

TRANSFER_CATEGORY = "Internal transfers"
UNCATEGORISED = "Uncategorised"

# NAB's categories as they appear in its exports, plus a few common income ones.
DEFAULT_CATEGORIES: list[tuple[str, str]] = (
    [
        (n, "expense")
        for n in [
            "Alcohol",
            "Attractions & events",
            "Cafe & coffee",
            "Cash",
            "Clothing & accessories",
            "Electronics & technology",
            "Fees",
            "Fuel",
            "Gifts",
            "Government",
            "Groceries",
            "Home improvements",
            "Homeware",
            "Insurance",
            "Loans",
            "Media",
            "Medical",
            "Other shopping",
            "Parking & tolls",
            "Personal care",
            "Pets",
            "Phone & internet",
            "Restaurants & takeaway",
            "Services",
            "Subscriptions",
            "Taxis & ride shares",
            "Travel expenses",
            "Uncategorised",
            "Vehicle expenses",
            "Education",
            "Rent",
            "Utilities",
        ]
    ]
    + [("Salary", "income"), ("Interest", "income"), ("Refund", "income"), ("Other income", "income")]
    + [(TRANSFER_CATEGORY, "transfer")]
)


def ensure_default_categories(db: Session) -> None:
    existing = set(db.scalars(select(Category.name).where(Category.group_id.is_(None))).all())
    for name, kind in DEFAULT_CATEGORIES:
        if name not in existing:
            db.add(Category(group_id=None, name=name, kind=kind))
    db.commit()


def visible_categories(db: Session, group_id: uuid.UUID) -> list[Category]:
    """The built-in categories plus the group's own, ordered by name."""
    return list(
        db.scalars(
            select(Category)
            .where(or_(Category.group_id.is_(None), Category.group_id == group_id))
            .order_by(Category.name)
        ).all()
    )


def get_or_create_category(db: Session, group_id: uuid.UUID, name: str, kind: str = "expense") -> Category:
    name = name.strip()
    for c in visible_categories(db, group_id):
        if c.name.lower() == name.lower():
            return c
    c = Category(group_id=group_id, name=name, kind=kind)
    db.add(c)
    db.flush()
    return c


@dataclass
class _CompiledRule:
    rule: CategoryRule
    regex: re.Pattern | None

    def matches(self, text: str) -> bool:
        if self.regex is not None:
            return bool(self.regex.search(text))
        return self.rule.pattern.lower() in text.lower()


class Categoriser:
    """Resolves categories for one group. Build once per import or re-categorisation run."""

    def __init__(self, db: Session, group_id: uuid.UUID):
        self.by_name = {c.name.lower(): c for c in visible_categories(db, group_id)}
        self.rules: list[_CompiledRule] = []
        for r in db.scalars(
            select(CategoryRule)
            .where(CategoryRule.group_id == group_id)
            .order_by(CategoryRule.priority, CategoryRule.created_at)
        ):
            regex = None
            if r.is_regex:
                try:
                    regex = re.compile(r.pattern, re.IGNORECASE)
                except re.error:
                    continue  # an invalid pattern is skipped, never fatal
            self.rules.append(_CompiledRule(r, regex))
        self.transfer = self.by_name.get(TRANSFER_CATEGORY.lower())
        self.uncategorised = self.by_name.get(UNCATEGORISED.lower())

    def resolve(
        self, *, description: str, merchant: str | None, bank_category: str | None, is_transfer: bool
    ) -> tuple[uuid.UUID | None, str]:
        if is_transfer and self.transfer is not None:
            return self.transfer.id, "bank"
        text = f"{merchant or ''} {description}"
        for cr in self.rules:
            if cr.matches(text):
                return cr.rule.category_id, "rule"
        if bank_category:
            c = self.by_name.get(bank_category.strip().lower())
            if c is not None:
                return c.id, "bank"
        return (self.uncategorised.id if self.uncategorised else None), "bank"


def validate_regex(pattern: str) -> str | None:
    try:
        re.compile(pattern)
    except re.error as e:
        return f"Not a valid pattern: {e}"
    return None
