"""Budget structure: headings (e.g. "Faste udgifter") hold posts (e.g. "Groceries og wine"), and each post
covers one or more categories with a monthly amount. A category belongs to at most one post."""

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.models import new_id
from app.db import Base

COLOR_SLOTS = 8  # categorical colour slots in the web app's palette


class BudgetHeading(Base):
    __tablename__ = "budget_headings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    position: Mapped[int] = mapped_column(Integer, default=0)


class BudgetPost(Base):
    __tablename__ = "budget_posts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    heading_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget_headings.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[int] = mapped_column(Integer, default=1)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # None = no amount set yet: spending is tracked, but nothing is over or under.
    monthly_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class BudgetPostCategory(Base):
    __tablename__ = "budget_post_categories"
    __table_args__ = (UniqueConstraint("group_id", "category_id", name="uq_budget_category_once"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    post_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("budget_posts.id", ondelete="CASCADE"), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
