"""Add session management fields to conversations table.

Revision ID: 006
Revises: 005
Create Date: 2026-03-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("is_expired", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "conversations",
        sa.Column("summary", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "summary")
    op.drop_column("conversations", "is_expired")
