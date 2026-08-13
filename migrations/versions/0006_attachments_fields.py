"""Add editors, custom fields and supplementary attachments."""

import sqlalchemy as sa
from alembic import op

from quirebase.db import Base

revision = "0006_attachments_fields"
down_revision = "0005_team_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("items")}
    if "editors" not in columns:
        op.add_column("items", sa.Column("editors", sa.Text(), nullable=True))
    if "custom_fields" not in columns:
        op.add_column("items", sa.Column("custom_fields", sa.Text(), nullable=True))
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("attachments")
    op.drop_column("items", "custom_fields")
    op.drop_column("items", "editors")
