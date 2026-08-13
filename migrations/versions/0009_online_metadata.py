"""Add structured external identifiers for online metadata imports."""

import sqlalchemy as sa
from alembic import op

revision = "0009_online_metadata"
down_revision = "0008_shared_pdf_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("items")}
    if "identifiers" not in columns:
        op.add_column("items", sa.Column("identifiers", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("items", "identifiers")
