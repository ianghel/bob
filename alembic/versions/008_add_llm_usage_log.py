"""Add llm_usage_log table for cost tracking.

Revision ID: 008
Revises: 007
Create Date: 2026-03-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("call_type", sa.String(20), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_usage_period", "llm_usage_log", ["period"])


def downgrade() -> None:
    op.drop_index("ix_usage_period", table_name="llm_usage_log")
    op.drop_table("llm_usage_log")
