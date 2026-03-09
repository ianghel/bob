"""Add global unique index on users.email.

Revision ID: 004
Revises: 003
Create Date: 2026-03-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("uq_user_email_global", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_user_email_global", table_name="users")
