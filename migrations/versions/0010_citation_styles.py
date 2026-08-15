"""Store user-defined CSL citation styles."""

from alembic import op

from quirebase.models import Base

revision = "0010_citation_styles"
down_revision = "0009_item_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("citation_styles")
