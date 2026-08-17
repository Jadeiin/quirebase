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
        sa.column("authors", sa.String),
        sa.column("editors", sa.String),
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
    doi_rows = [
        {
            "id": str(uuid.uuid4()),
            "item_id": row[0],
            "provider": "doi",
            "value": row[1].strip(),
            "created_at": now_utc,
        }
        for row in existing_items
        if row[1] and row[1].strip()
    ]
    if doi_rows:
        bind.execute(identifiers_table.insert(), doi_rows)

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

    # Preload existing authors keyed like find_or_create_author matches them:
    # case-insensitive exact match on last/first name (None = no first name).
    author_ids: dict[tuple[str, str | None], str] = {}
    for row in bind.execute(
        sa.select(authors_table.c.id, authors_table.c.last_name, authors_table.c.first_name)
    ).fetchall():
        author_ids[row[1].lower(), row[2].lower() if row[2] else None] = row[0]

    def author_id_for(last_name: str, first_name: str | None) -> str:
        key = (last_name.lower(), first_name.lower() if first_name else None)
        author_id = author_ids.get(key)
        if author_id is None:
            author_id = str(uuid.uuid4())
            author_ids[key] = author_id
            bind.execute(
                authors_table.insert().values(
                    id=author_id,
                    last_name=last_name,
                    first_name=first_name,
                    created_at=now_utc,
                )
            )
        return author_id

    items_with_authors = bind.execute(
        sa.select(items_table.c.id, items_table.c.authors, items_table.c.editors)
    ).fetchall()

    link_rows: list[dict] = []
    for item_row in items_with_authors:
        item_id = item_row[0]
        for role, raw in (("author", item_row[1]), ("editor", item_row[2])):
            if not (raw and raw.strip()):
                continue
            linked_author_ids: set[str] = set()
            for pos, name in enumerate(raw.split(";"), start=1):
                if not name.strip():
                    continue
                last, first = parse_author_name(name.strip())
                author_id = author_id_for(last, first)
                if author_id in linked_author_ids:
                    continue
                linked_author_ids.add(author_id)
                link_rows.append({
                    "id": str(uuid.uuid4()),
                    "item_id": item_id,
                    "author_id": author_id,
                    "position": pos,
                    "role": role,
                    "is_corresponding": False,
                })
    if link_rows:
        bind.execute(item_authors_table.insert(), link_rows)


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
