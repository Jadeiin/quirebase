"""Add rich bibliographic metadata columns, structured authors, and identifiers."""

import sqlalchemy as sa
from alembic import op

from quirebase.core.database import Base

revision = "0012_rich_metadata_authors_and_uids"
down_revision = "0011_system_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("items")}
    new_columns = [
        ("volume", sa.Column("volume", sa.String(100), nullable=True)),
        ("issue", sa.Column("issue", sa.String(100), nullable=True)),
        ("pages", sa.Column("pages", sa.String(100), nullable=True)),
        ("affiliation", sa.Column("affiliation", sa.Text(), nullable=True)),
        ("publisher", sa.Column("publisher", sa.Text(), nullable=True)),
        ("place_published", sa.Column("place_published", sa.String(255), nullable=True)),
        ("journal_abbreviation", sa.Column("journal_abbreviation", sa.Text(), nullable=True)),
        ("bibtex_id", sa.Column("bibtex_id", sa.String(255), nullable=True)),
        ("bibtex_type", sa.Column("bibtex_type", sa.String(40), nullable=True)),
        ("urls", sa.Column("urls", sa.Text(), nullable=True)),
        (
            "updated_by",
            sa.Column(
                "updated_by",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        ),
    ]
    for col_name, col_obj in new_columns:
        if col_name not in columns:
            op.add_column("items", col_obj)

    Base.metadata.create_all(bind=op.get_bind())

    # Backfill existing DOIs to item_identifiers
    bind = op.get_bind()
    items_table = sa.table(
        "items",
        sa.column("id", sa.String),
        sa.column("doi", sa.String),
    )
    identifiers_table = sa.table(
        "item_identifiers",
        sa.column("id", sa.String),
        sa.column("item_id", sa.String),
        sa.column("provider", sa.String),
        sa.column("value", sa.String),
    )
    import uuid

    existing_items = bind.execute(
        sa.select(items_table.c.id, items_table.c.doi).where(items_table.c.doi.is_not(None))
    ).fetchall()
    for row in existing_items:
        if row[1] and row[1].strip():
            bind.execute(
                identifiers_table.insert().values(
                    id=str(uuid.uuid4()),
                    item_id=row[0],
                    provider="doi",
                    value=row[1].strip(),
                )
            )


def downgrade() -> None:
    op.drop_table("item_identifiers")
    op.drop_table("item_authors")
    op.drop_table("authors")
    for col_name in [
        "updated_by",
        "urls",
        "bibtex_type",
        "bibtex_id",
        "journal_abbreviation",
        "place_published",
        "publisher",
        "affiliation",
        "pages",
        "issue",
        "volume",
    ]:
        op.drop_column("items", col_name)
