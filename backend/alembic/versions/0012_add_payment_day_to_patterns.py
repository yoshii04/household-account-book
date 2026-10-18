"""add payment_day_of_month and payment_month_of_year to transaction_patterns

Revision ID: 0012
Revises: 0011, ed0f72bb40b4
Create Date: 2026-05-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, tuple] = ("0011", "ed0f72bb40b4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transaction_patterns",
        sa.Column("payment_day_of_month", sa.Integer(), nullable=True),
    )
    op.add_column(
        "transaction_patterns",
        sa.Column("payment_month_of_year", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("transaction_patterns", "payment_month_of_year")
    op.drop_column("transaction_patterns", "payment_day_of_month")
