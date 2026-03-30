"""Add log_entries table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "log_entries",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("level", sa.String(10), nullable=False),
        sa.Column("logger_name", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_log_entries_timestamp", "log_entries", [sa.text("timestamp DESC")]
    )
    op.create_index("idx_log_entries_level", "log_entries", ["level"])
    op.create_index("idx_log_entries_source", "log_entries", ["source"])


def downgrade() -> None:
    op.drop_table("log_entries")
