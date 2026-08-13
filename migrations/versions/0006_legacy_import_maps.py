"""Add idempotency mappings for read-only legacy imports."""

from alembic import op

from quirebase.db import Base

revision = "0006_legacy_import_maps"
down_revision = "0005_team_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("legacy_import_maps")
