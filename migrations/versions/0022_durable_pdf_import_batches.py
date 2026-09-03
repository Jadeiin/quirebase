"""Track durable PDF Import Batch preparation.

Revision ID: 0022_durable_pdf_import_batches
Revises: 0021_object_integrity_metrics
"""

import sqlalchemy as sa
from alembic import op

revision = "0022_durable_pdf_import_batches"
down_revision = "0021_object_integrity_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("import_batches")}
    indexes = {index["name"] for index in inspector.get_indexes("import_batches")}
    with op.batch_alter_table("import_batches") as batch:
        if "status" not in columns:
            batch.add_column(
                sa.Column("status", sa.String(length=16), nullable=False, server_default="ready")
            )
        if "workflow_id" not in columns:
            batch.add_column(sa.Column("workflow_id", sa.String(length=255), nullable=True))
        if "ix_import_batches_workflow_id" not in indexes:
            batch.create_index("ix_import_batches_workflow_id", ["workflow_id"])


def downgrade() -> None:
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_index("ix_import_batches_workflow_id")
        batch.drop_column("workflow_id")
        batch.drop_column("status")
