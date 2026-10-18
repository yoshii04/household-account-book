"""re-add start_date and initial_balance to accounts

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-21

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("accounts", sa.Column("initial_balance", sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("accounts", "initial_balance")
    op.drop_column("accounts", "start_date")
