"""Store the native PDF annotation policy selected for an Import Batch."""

import sqlalchemy as sa
from alembic import op

revision = "0028_pdf_import_annotation_mode"
down_revision = "0027_annotation_object_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_batches" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("import_batches")}
    with op.batch_alter_table("import_batches") as batch:
        if "pdf_annotation_mode" not in columns:
            batch.add_column(sa.Column("pdf_annotation_mode", sa.String(length=16), nullable=True))
        batch.create_check_constraint(
            "ck_import_batches_pdf_annotation_mode",
            "pdf_annotation_mode IS NULL OR pdf_annotation_mode IN ('preserve', 'strip', 'import')",
        )


def downgrade() -> None:
    if "import_batches" not in sa.inspect(op.get_bind()).get_table_names():
        return
    with op.batch_alter_table("import_batches") as batch:
        batch.drop_constraint("ck_import_batches_pdf_annotation_mode", type_="check")
        batch.drop_column("pdf_annotation_mode")
