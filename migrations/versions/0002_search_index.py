"""Add the dialect-native full-text search index."""

from alembic import op

revision = "0002_search_index"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE TABLE item_search (
                item_id varchar(36) PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                document tsvector NOT NULL
            )
            """
        )
        op.execute("CREATE INDEX ix_item_search_document ON item_search USING gin(document)")
    else:
        op.execute(
            """
            CREATE VIRTUAL TABLE item_search USING fts5(
                item_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE item_search")
