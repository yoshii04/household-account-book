"""add_to_account_id_to_transaction_patterns

Revision ID: ed0f72bb40b4
Revises: 0009
Create Date: 2026-05-19 01:26:07.409089

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ed0f72bb40b4'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('transaction_patterns', sa.Column('to_account_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_transaction_patterns_to_account_id',
        'transaction_patterns', 'accounts',
        ['to_account_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_transaction_patterns_to_account_id', 'transaction_patterns', type_='foreignkey')
    op.drop_column('transaction_patterns', 'to_account_id')
