"""Scope caller-provided upload operation identities per owner and Item."""

import sqlalchemy as sa
from alembic import op

revision = "0031_upload_operation_identity"
down_revision = "0030_scoped_import_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, name in (
        ("file_revisions", "uq_file_revisions_owner_item_operation"),
        ("attachments", "uq_attachments_owner_item_operation"),
    ):
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        existing = {
            constraint.get("name") for constraint in inspector.get_unique_constraints(table)
        }
        if {"created_by", "item_id", "operation_id"} <= columns and name not in existing:
            with op.batch_alter_table(table) as batch:
                batch.create_unique_constraint(name, ["created_by", "item_id", "operation_id"])


def downgrade() -> None:
    raise RuntimeError("0031_upload_operation_identity is forward-only")
