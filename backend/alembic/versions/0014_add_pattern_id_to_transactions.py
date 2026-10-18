"""add_pattern_id_to_transactions

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0014'
down_revision: Union[str, None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transactions', sa.Column('pattern_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_transactions_pattern_id',
        'transactions', 'transaction_patterns',
        ['pattern_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_transactions_pattern_id', 'transactions', type_='foreignkey')
    op.drop_column('transactions', 'pattern_id')
