"""rename audit authorization capability to resource action

Revision ID: de32f77d4d0b
Revises: 5c1d5e851c78
Create Date: 2026-09-28 01:05:10.918016

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'de32f77d4d0b'
down_revision: Union[str, Sequence[str], None] = '5c1d5e851c78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "audit_events",
        "authorization_capability",
        new_column_name="authorization_resource_action",
        existing_type=sa.String(length=80),
        existing_nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "audit_events",
        "authorization_resource_action",
        new_column_name="authorization_capability",
        existing_type=sa.String(length=80),
        existing_nullable=True,
    )
