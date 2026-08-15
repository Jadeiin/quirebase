"""Add tags and item discussions."""

from alembic import op

from quirebase.core.database import Base

revision = "0004_tags_discussions"
down_revision = "0003_bibliography_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("discussion_messages")
    op.drop_table("item_tags")
    op.drop_table("tags")
