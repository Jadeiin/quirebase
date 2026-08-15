"""Add system settings table for dynamic runtime configuration."""

from alembic import op

from quirebase.models import Base

revision = "0011_system_settings"
down_revision = "0010_citation_styles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("system_settings")
