"""The core data model.

Every financial record belongs to a group (for example a family). Users join groups through a
membership with a role. API code must always filter by group_id; see app.core.deps.group_access.

Some columns and tables are prepared for the AI coach (increment 3) and are not used or exposed
in increment 1: Transaction.value_tag, Goal, ValueProfile and User.ai_consent.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC so comparisons work on both databases."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


# Allowed values, kept as plain strings so the database stays portable and readable.
ROLES = ("owner", "member")
ACCOUNT_KINDS = ("transaction", "credit_card")  # savings, loan, super, investment come later
CATEGORY_KINDS = ("expense", "income", "transfer")
# Who decided a category or value tag. A user's choice always wins over the others.
SOURCES = ("bank", "rule", "user", "coach")
# Hidden in increment 1, filled automatically by the AI coach later.
VALUE_TAGS = ("valued", "necessity", "drift")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    locale: Mapped[str] = mapped_column(String(16), default="en-AU")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Consent to send this user's data to an AI model. Off until the user turns it on.
    ai_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Group(Base):
    """A household or family. The unit that owns accounts, transactions, categories and rules."""

    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    base_currency: Mapped[str] = mapped_column(String(3), default="AUD")
    locale: Mapped[str] = mapped_column(String(16), default="en-AU")
    timezone: Mapped[str] = mapped_column(String(64), default="Australia/Melbourne")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="group", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id"),
        CheckConstraint(f"role IN {ROLES}", name="ck_membership_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16), default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship(back_populates="memberships")
    group: Mapped[Group] = relationship(back_populates="memberships")


class Invite(Base):
    """A one-time code that lets another person join a group."""

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16), default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    """A signed-in browser. Only a hash of the cookie token is stored."""

    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class LoginAttempt(Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_email_at", "email", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    success: Mapped[bool] = mapped_column(Boolean)


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("group_id", "institution", "external_ref"),
        CheckConstraint(f"kind IN {ACCOUNT_KINDS}", name="ck_account_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    # The person the account or card belongs to, if known. Shared accounts leave it empty.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    institution: Mapped[str] = mapped_column(String(64), default="NAB")
    # How the bank identifies the account in its exports, e.g. "Card ending 3528".
    external_ref: Mapped[str] = mapped_column(String(120))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Category(Base):
    """A spending category. group_id is empty for the built-in defaults shared by all groups."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("group_id", "name"),
        CheckConstraint(f"kind IN {CATEGORY_KINDS}", name="ck_category_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16), default="expense")


class CategoryRule(Base):
    """Puts transactions whose text matches a pattern into a category. Lower priority runs first."""

    __tablename__ = "category_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    # Case-insensitive text to look for. Plain text by default; a regular expression if is_regex.
    pattern: Mapped[str] = mapped_column(String(200))
    is_regex: Mapped[bool] = mapped_column(Boolean, default=False)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    priority: Mapped[int] = mapped_column(Integer, default=100)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(32))  # "nab_csv" now; "basiq" etc. later
    filename: Mapped[str | None] = mapped_column(String(255))
    imported_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_new: Mapped[int] = mapped_column(Integer, default=0)
    rows_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    rows_pending_replaced: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "fingerprint"),
        Index("ix_transactions_group_date", "group_id", "posted_date"),
        CheckConstraint(f"category_source IN {SOURCES}", name="ck_tx_category_source"),
        CheckConstraint(f"value_tag IS NULL OR value_tag IN {VALUE_TAGS}", name="ck_tx_value_tag"),
        CheckConstraint(f"value_tag_source IS NULL OR value_tag_source IN {SOURCES}", name="ck_tx_value_tag_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("import_batches.id", ondelete="SET NULL"))

    posted_date: Mapped[date] = mapped_column(Date)
    # Negative = money out, positive = money in, in the account's currency.
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    description: Mapped[str] = mapped_column(Text)
    merchant: Mapped[str | None] = mapped_column(String(200))
    bank_type: Mapped[str | None] = mapped_column(String(64))  # e.g. "CREDIT CARD PURCHASE"
    bank_category: Mapped[str | None] = mapped_column(String(80))  # the bank's own category
    balance_after: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_pending: Mapped[bool] = mapped_column(Boolean, default=False)

    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    category_source: Mapped[str] = mapped_column(String(16), default="bank")

    # Money moving between the group's own accounts (e.g. paying the credit card). Not spending.
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_pair_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    # Prepared for the AI coach; always empty in increment 1.
    value_tag: Mapped[str | None] = mapped_column(String(16))
    value_tag_source: Mapped[str | None] = mapped_column(String(16))

    # Hash of the row's identifying fields, used to skip rows already imported.
    fingerprint: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Goal(Base):
    """Prepared for the AI coach (hidden in increment 1): a dream turned into a cost and a date."""

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    # Empty = shared by the group; set = one person's goal.
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(160))
    target_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3), default="AUD")
    target_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ValueProfile(Base):
    """Prepared for the AI coach (hidden): what a person or the whole group values, and coach settings."""

    __tablename__ = "value_profiles"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    # Empty = the group's shared profile.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    values: Mapped[dict] = mapped_column(JSON, default=dict)
    coach_persona: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditEvent(Base):
    """An activity log of security-relevant and data-changing actions."""

    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_group_at", "group_id", "at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)


class ImportProfile(Base):
    """A CSV layout a group has taught the app once: which column is the date, the amount and so on.

    Found again by the file's header, so the next file from the same bank imports without questions.
    """

    __tablename__ = "import_profiles"
    __table_args__ = (UniqueConstraint("group_id", "header_signature", name="uq_import_profile_header"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    header_signature: Mapped[str] = mapped_column(String(64))
    mapping: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
