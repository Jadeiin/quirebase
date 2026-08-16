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
        sa.column("created_at", sa.DateTime),
    )
    import uuid
    from datetime import UTC, datetime

    now_utc = datetime.now(UTC)

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
                    created_at=now_utc,
                )
            )

    # Backfill existing authors into authors and item_authors tables
    authors_table = sa.table(
        "authors",
        sa.column("id", sa.String),
        sa.column("first_name", sa.String),
        sa.column("last_name", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    item_authors_table = sa.table(
        "item_authors",
        sa.column("id", sa.String),
        sa.column("item_id", sa.String),
        sa.column("author_id", sa.String),
        sa.column("position", sa.Integer),
        sa.column("role", sa.String),
        sa.column("is_corresponding", sa.Boolean),
    )
    from quirebase.library.authors import parse_author_name

    items_with_authors = bind.execute(
        sa.select(
            items_table.c.id, sa.column("authors", sa.String), sa.column("editors", sa.String)
        ).select_from(
            sa.table(
                "items",
                sa.column("id", sa.String),
                sa.column("authors", sa.String),
                sa.column("editors", sa.String),
            )
        )
    ).fetchall()

    for item_row in items_with_authors:
        item_id = item_row[0]
        raw_authors = item_row[1]
        raw_editors = item_row[2] if len(item_row) > 2 else None

        if raw_authors and raw_authors.strip():
            for pos, a_str in enumerate(raw_authors.split(";"), start=1):
                if a_str.strip():
                    last, first = parse_author_name(a_str.strip())
                    existing_author = bind.execute(
                        sa.select(authors_table.c.id).where(
                            authors_table.c.last_name == last,
                            authors_table.c.first_name == first
                            if first
                            else authors_table.c.first_name.is_(None),
                        )
                    ).scalar()
                    if not existing_author:
                        author_id = str(uuid.uuid4())
                        bind.execute(
                            authors_table.insert().values(
                                id=author_id,
                                last_name=last,
                                first_name=first,
                                created_at=now_utc,
                            )
                        )
                    else:
                        author_id = existing_author
                    bind.execute(
                        item_authors_table.insert().values(
                            id=str(uuid.uuid4()),
                            item_id=item_id,
                            author_id=author_id,
                            position=pos,
                            role="author",
                            is_corresponding=False,
                        )
                    )

        if raw_editors and raw_editors.strip():
            for pos, e_str in enumerate(raw_editors.split(";"), start=1):
                if e_str.strip():
                    last, first = parse_author_name(e_str.strip())
                    existing_author = bind.execute(
                        sa.select(authors_table.c.id).where(
                            authors_table.c.last_name == last,
                            authors_table.c.first_name == first
                            if first
                            else authors_table.c.first_name.is_(None),
                        )
                    ).scalar()
                    if not existing_author:
                        author_id = str(uuid.uuid4())
                        bind.execute(
                            authors_table.insert().values(
                                id=author_id,
                                last_name=last,
                                first_name=first,
                                created_at=now_utc,
                            )
                        )
                    else:
                        author_id = existing_author
                    bind.execute(
                        item_authors_table.insert().values(
                            id=str(uuid.uuid4()),
                            item_id=item_id,
                            author_id=author_id,
                            position=pos,
                            role="editor",
                            is_corresponding=False,
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
