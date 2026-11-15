"""Built-in categories. How a transaction gets one is in app.core.categorisation."""

import re
import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.models import Category

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


def validate_regex(pattern: str) -> str | None:
    try:
        re.compile(pattern)
    except re.error as e:
        return f"Not a valid pattern: {e}"
    return None
