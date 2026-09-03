"""Constrain Import Batch durable states.

Revision ID: 0023_import_batch_status_constraint
Revises: 0022_durable_pdf_import_batches
"""

from alembic import op

revision = "0023_import_batch_status_constraint"
down_revision = "0022_durable_pdf_import_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("import_batches") as batch:
        batch.create_check_constraint(
            "ck_import_batches_status",
            "status IN ('pending', 'ready', 'failed')",
        )


def downgrade() -> None:
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_constraint("ck_import_batches_status", type_="check")
