"""remove login session csrf token

Revision ID: d779adef15bf
Revises: a2254a6c211f
Create Date: 2026-09-16 01:37:20.317658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd779adef15bf'
down_revision: Union[str, Sequence[str], None] = 'a2254a6c211f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("login_sessions", "csrf_token")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "login_sessions",
        sa.Column("csrf_token", sa.String(length=64), nullable=False, server_default=""),
    )
