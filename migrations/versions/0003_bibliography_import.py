"""Add bibliography fields and staged import batches."""

import sqlalchemy as sa
from alembic import op

revision = "0003_bibliography_import"
down_revision = "0002_search_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("items")}
    additions = (
        ("publication_title", sa.Column("publication_title", sa.Text(), nullable=True)),
        ("doi", sa.Column("doi", sa.String(length=500), nullable=True)),
        ("reference_type", sa.Column("reference_type", sa.String(length=40), nullable=True)),
    )
    for name, column in additions:
        if name not in columns:
            op.add_column("items", column)
    indexes = {index["name"] for index in inspector.get_indexes("items")}
    if "ix_items_doi" not in indexes:
        op.create_index("ix_items_doi", "items", ["doi"])
    if not inspector.has_table("import_batches"):
        op.create_table(
            "import_batches",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("file_format", sa.String(length=16), nullable=False),
            sa.Column("records", sa.Text(), nullable=False),
            sa.Column("errors", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_import_batches_owner_id", "import_batches", ["owner_id"])
        op.create_index("ix_import_batches_created_at", "import_batches", ["created_at"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("import_batches"):
        op.drop_table("import_batches")
    columns = {column["name"] for column in inspector.get_columns("items")}
    indexes = {index["name"] for index in inspector.get_indexes("items")}
    if "ix_items_doi" in indexes:
        op.drop_index("ix_items_doi", table_name="items")
    for name in ("reference_type", "doi", "publication_title"):
        if name in columns:
            op.drop_column("items", name)
