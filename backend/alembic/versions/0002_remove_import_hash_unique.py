"""remove import_hash unique constraint

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-11

"""
from typing import Sequence, Union
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("transactions_import_hash_key", "transactions", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("transactions_import_hash_key", "transactions", ["import_hash"])
