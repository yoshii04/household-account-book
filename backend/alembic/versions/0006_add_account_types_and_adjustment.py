"""add account_types table and adjustment_amount to accounts

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_account_types_code"),
    )
    op.execute(
        """
        INSERT INTO account_types (code, label, sort_order) VALUES
        ('cash',    '現金',       10),
        ('bank',    '銀行',       20),
        ('card',    'カード',     30),
        ('e-money', '電子マネー', 40),
        ('other',   'その他',     50)
        """
    )
    op.add_column(
        "accounts",
        sa.Column("adjustment_amount", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("accounts", "adjustment_amount")
    op.drop_table("account_types")
