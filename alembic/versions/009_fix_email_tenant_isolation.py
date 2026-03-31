"""Fix email tenant isolation: scope message_id uniqueness to tenant+user.

Revision ID: 009
Revises: 008
Create Date: 2026-03-31
"""

from typing import Sequence, Union

from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the global unique index on message_id (created by unique=True on column)
    op.drop_constraint("message_id", "email_digests", type_="unique")
    # Re-create as a plain index for lookup performance
    op.create_index("ix_email_digests_message_id", "email_digests", ["message_id"])
    # Add tenant+user scoped uniqueness so two users can have the same message_id
    op.create_unique_constraint(
        "uq_tenant_user_message", "email_digests", ["tenant_id", "user_id", "message_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_tenant_user_message", "email_digests", type_="unique")
    op.drop_index("ix_email_digests_message_id", table_name="email_digests")
    op.create_index("message_id", "email_digests", ["message_id"], unique=True)
