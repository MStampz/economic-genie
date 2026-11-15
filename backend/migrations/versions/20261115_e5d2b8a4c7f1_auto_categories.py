"""Automatic categorisation: an "auto" source and the reason behind each automatic category

Revision ID: e5d2b8a4c7f1
Revises: c3f1a7e2b9d4
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5d2b8a4c7f1"
down_revision: str | Sequence[str] | None = "c3f1a7e2b9d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = "('bank', 'rule', 'auto', 'user', 'coach')"
OLD = "('bank', 'rule', 'user', 'coach')"


def _sources(values: str) -> None:
    with op.batch_alter_table("transactions") as b:
        b.drop_constraint("ck_tx_category_source", type_="check")
        b.drop_constraint("ck_tx_value_tag_source", type_="check")
        b.create_check_constraint("ck_tx_category_source", f"category_source IN {values}")
        b.create_check_constraint("ck_tx_value_tag_source", f"value_tag_source IS NULL OR value_tag_source IN {values}")


def upgrade() -> None:
    op.add_column("transactions", sa.Column("category_reason", sa.String(length=200), nullable=True))
    _sources(NEW)
    # NAB's "Credit card repayments" on the transaction account is money moving to the family's own card.
    op.execute(
        """
        UPDATE transactions SET source_transfer = TRUE,
               is_internal_transfer = CASE WHEN transfer_user IS NULL THEN TRUE ELSE is_internal_transfer END
        WHERE lower(coalesce(bank_category, '')) = 'credit card repayments'
        """
    )


def downgrade() -> None:
    op.execute("UPDATE transactions SET category_source = 'rule' WHERE category_source = 'auto'")
    op.execute("UPDATE transactions SET value_tag_source = 'rule' WHERE value_tag_source = 'auto'")
    _sources(OLD)
    op.drop_column("transactions", "category_reason")
