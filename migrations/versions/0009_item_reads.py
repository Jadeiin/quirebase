"""Track recently opened papers per account."""

from alembic import op

from quirebase.core.database import Base

revision = "0009_item_reads"
down_revision = "0008_online_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("item_reads")
