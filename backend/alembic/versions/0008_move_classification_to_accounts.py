"""move classification from account_types to accounts

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("account_types", "classification")
    op.add_column(
        "accounts",
        sa.Column("classification", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("accounts", "classification")
    op.add_column(
        "account_types",
        sa.Column("classification", sa.String(100), nullable=True),
    )
