"""Persist the effective PDF size limit for durable import workflows."""

import sqlalchemy as sa
from alembic import op

revision = "0029_import_batch_pdf_size_limit"
down_revision = "0028_pdf_import_annotation_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_batches" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("import_batches")}
    if "max_pdf_bytes" not in columns:
        with op.batch_alter_table("import_batches") as batch:
            batch.add_column(sa.Column("max_pdf_bytes", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "import_batches" not in sa.inspect(op.get_bind()).get_table_names():
        return
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_column("max_pdf_bytes")
