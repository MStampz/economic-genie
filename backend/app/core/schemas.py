import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---- users and auth


class RegisterIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)
    display_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValueError("Enter a valid email address.")
        return v


class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=200)

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class MembershipOut(Out):
    group_id: uuid.UUID
    group_name: str
    role: str


class UserOut(Out):
    id: uuid.UUID
    email: str
    display_name: str
    locale: str


class MeOut(BaseModel):
    user: UserOut
    groups: list[MembershipOut]


# ---- groups


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="AUD", min_length=3, max_length=3)
    locale: str = Field(default="en-AU", max_length=16)
    timezone: str = Field(default="Australia/Melbourne", max_length=64)

    @field_validator("base_currency")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.upper()


class GroupOut(Out):
    id: uuid.UUID
    name: str
    base_currency: str
    locale: str
    timezone: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: str
    email: str
    role: str
    joined_at: datetime


class InviteOut(BaseModel):
    code: str
    expires_at: datetime


class JoinIn(BaseModel):
    code: str = Field(min_length=4, max_length=64)


class RoleIn(BaseModel):
    role: Literal["owner", "member"]


# ---- accounts, categories, rules, transactions


class AccountOut(Out):
    id: uuid.UUID
    name: str
    kind: str
    institution: str
    external_ref: str
    currency: str
    owner_user_id: uuid.UUID | None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    owner_user_id: uuid.UUID | None = None
    clear_owner: bool = False


class CategoryOut(Out):
    id: uuid.UUID
    name: str
    kind: str
    group_id: uuid.UUID | None


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["expense", "income", "transfer"] = "expense"


class RuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=200)
    is_regex: bool = False
    category_id: uuid.UUID
    priority: int = Field(default=100, ge=0, le=10000)


class RuleOut(Out):
    id: uuid.UUID
    pattern: str
    is_regex: bool
    category_id: uuid.UUID
    priority: int


class TransactionOut(Out):
    id: uuid.UUID
    account_id: uuid.UUID
    posted_date: date
    amount: Decimal
    currency: str
    description: str
    merchant: str | None
    bank_type: str | None
    bank_category: str | None
    is_pending: bool
    category_id: uuid.UUID | None
    category_source: str
    is_internal_transfer: bool
    transfer_user: bool | None
    import_batch_id: uuid.UUID | None


class TransactionPage(BaseModel):
    items: list[TransactionOut]
    total: int


class TransactionPatch(BaseModel):
    """Only the fields sent change."""

    # Set a category by hand, or null to hand the transaction back to the rules and the bank.
    category_id: uuid.UUID | None = None
    # True = a transfer between the group's own accounts, False = never one, null = let the app decide.
    is_transfer: bool | None = None


class ImportResult(BaseModel):
    batch_id: uuid.UUID
    rows_total: int
    rows_new: int
    rows_duplicate: int
    rows_pending_replaced: int
    accounts_created: list[str]
    accounts: list[str]
    transfers_paired: int
    format: str
    filename: str | None


class ApplyRulesResult(BaseModel):
    updated: int


class AuditOut(Out):
    at: datetime
    action: str
    user_id: uuid.UUID | None
    detail: dict | None
