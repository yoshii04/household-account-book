"""add pattern_groups table and pattern_group_id to transaction_patterns

Revision ID: 0010
Revises: ed0f72bb40b4
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, None] = "ed0f72bb40b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pattern_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_pattern_groups_name"),
    )

    op.add_column(
        "transaction_patterns",
        sa.Column("pattern_group_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_transaction_patterns_pattern_group_id",
        "transaction_patterns", "pattern_groups",
        ["pattern_group_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_transaction_patterns_pattern_group_id",
        "transaction_patterns",
        type_="foreignkey",
    )
    op.drop_column("transaction_patterns", "pattern_group_id")
    op.drop_table("pattern_groups")
