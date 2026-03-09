"""Add is_approved column to users table.

Revision ID: 002
Revises: 001
Create Date: 2026-03-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default="1" so existing users are auto-approved.
    # New users created via SQLAlchemy ORM will get default=False.
    op.add_column(
        "users",
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("users", "is_approved")
