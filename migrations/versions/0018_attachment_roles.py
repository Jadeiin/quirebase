"""Add distinguished Attachment roles for Item representative images."""

import sqlalchemy as sa
from alembic import op

revision = "0018_attachment_roles"
down_revision = "0017_api_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("attachments")}
    if "role" not in columns:
        with op.batch_alter_table("attachments") as batch:
            batch.add_column(sa.Column("role", sa.String(length=32), nullable=True))
            batch.create_check_constraint(
                "ck_attachments_role",
                "role IS NULL OR role = 'graphical_abstract'",
            )
            batch.create_unique_constraint("uq_attachments_item_role", ["item_id", "role"])


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("attachments")}
    if "role" in columns:
        with op.batch_alter_table("attachments") as batch:
            batch.drop_constraint("uq_attachments_item_role", type_="unique")
            batch.drop_constraint("ck_attachments_role", type_="check")
            batch.drop_column("role")
