"""Add invitations and durable login throttling."""

from alembic import op

from quirebase.db import Base

revision = "0005_team_accounts"
down_revision = "0004_tags_discussions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_table("login_throttles")
