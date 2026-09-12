"""Reserve owner-scoped Item creation operation identities after deletion."""

import sqlalchemy as sa
from alembic import op

revision = "0032_item_create_tombstones"
down_revision = "0031_upload_operation_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("item_create_tombstones"):
        return
    op.create_table(
        "item_create_tombstones",
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=255), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("created_by", "operation_id"),
    )


def downgrade() -> None:
    raise RuntimeError("0032_item_create_tombstones is forward-only")
