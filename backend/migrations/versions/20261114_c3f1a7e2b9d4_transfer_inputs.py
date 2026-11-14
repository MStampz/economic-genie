"""Keep what the bank said about a transfer apart from the matching, and let people override it

Revision ID: c3f1a7e2b9d4
Revises: ad6e36575b49
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f1a7e2b9d4"
down_revision: str | Sequence[str] | None = "ad6e36575b49"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("transactions", sa.Column("source_transfer", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("transactions", sa.Column("transfer_user", sa.Boolean(), nullable=True))
    # Rows the bank marked as transfers: unpaired transfers, plus the bank's own transfer types and categories.
    op.execute(
        """
        UPDATE transactions SET source_transfer = TRUE
        WHERE (is_internal_transfer AND transfer_pair_id IS NULL)
           OR upper(coalesce(bank_type, '')) = 'CREDIT CARD PAYMENT'
           OR lower(coalesce(bank_category, '')) IN ('internal transfers', 'internal transfer')
        """
    )


def downgrade() -> None:
    op.drop_column("transactions", "transfer_user")
    op.drop_column("transactions", "source_transfer")
