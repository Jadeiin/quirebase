"""Persist PDF import options and annotation diagnostics."""

import sqlalchemy as sa
from alembic import op

revision = "0028_pdf_import_annotation_mode"
down_revision = "0027_annotation_object_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "import_batches" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("import_batches")}
        with op.batch_alter_table("import_batches") as batch:
            if "pdf_annotation_mode" not in columns:
                batch.add_column(
                    sa.Column("pdf_annotation_mode", sa.String(length=16), nullable=True)
                )
            if "max_pdf_bytes" not in columns:
                batch.add_column(sa.Column("max_pdf_bytes", sa.Integer(), nullable=True))
            batch.create_check_constraint(
                "ck_import_batches_pdf_annotation_mode",
                "pdf_annotation_mode IS NULL OR pdf_annotation_mode IN ('preserve', 'strip', 'import')",
            )
    if "file_revisions" in inspector.get_table_names():
        revision_columns = {column["name"] for column in inspector.get_columns("file_revisions")}
        if "annotation_diagnostics" not in revision_columns:
            with op.batch_alter_table("file_revisions") as batch:
                batch.add_column(sa.Column("annotation_diagnostics", sa.Text(), nullable=True))


def downgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "import_batches" in tables:
        with op.batch_alter_table("import_batches") as batch:
            batch.drop_constraint("ck_import_batches_pdf_annotation_mode", type_="check")
            batch.drop_column("max_pdf_bytes")
            batch.drop_column("pdf_annotation_mode")
    if "file_revisions" in tables:
        with op.batch_alter_table("file_revisions") as batch:
            batch.drop_column("annotation_diagnostics")
