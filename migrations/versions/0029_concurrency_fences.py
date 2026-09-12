"""Add aggregate lifecycle fences, idempotency keys and import commit state.

This is the single forward-only migration for the concurrency PR.  The
follow-up schema changes (scoped upload identities, Item-create tombstones,
and Search projection generations) are intentionally folded into this
revision so a fresh deployment has one atomic upgrade boundary.

The fields in this migration deliberately live alongside the existing optimistic
``Item.version`` token. Version detects stale editor pages; lifecycle_fence,
aggregate_sequence and recommendation_sequence protect work that can finish
after the request that started it.

The migration also renames ``import_batches.owner_id`` to ``created_by`` to match
the repository-wide name for the creating user.
"""

import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "0029_concurrency_fences"
down_revision = "0028_project_management"
branch_labels = None
depends_on = None


def _has_table(bind, table: str) -> bool:
    return sa.inspect(bind).has_table(table)


def _columns(bind, table: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _has_named_index(bind, table: str, name: str) -> bool:
    if bind.dialect.name == "sqlite":
        return bool(
            bind.scalar(
                sa.text("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = :name"),
                {"name": name},
            )
        )
    return any(index["name"] == name for index in sa.inspect(bind).get_indexes(table))


def _set_sqlite_foreign_keys(bind, enabled: bool) -> None:
    """Toggle SQLite FK enforcement while no transaction is active.

    Alembic normally owns a migration transaction, in which case its
    autocommit block safely commits before changing the pragma.  Some tests
    and embedding callers invoke a revision directly with an already-open
    SQLAlchemy transaction; handle that shape explicitly so the pragma is
    still effective instead of silently leaving enforcement enabled.
    """

    statement = sa.text(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
    context = op.get_context()
    if getattr(context, "_transaction", None) is not None:
        with context.autocommit_block():
            op.execute(statement)
        return
    if bind.in_transaction():
        # A direct revision caller may have wrapped the connection in an
        # outer SQLAlchemy transaction context.  Commit the underlying DBAPI
        # transaction so the context object remains usable after the pragma
        # change (calling ``bind.commit()`` would close that outer context).
        driver = bind.connection.driver_connection
        driver.commit()
        driver.execute(str(statement))
    else:
        bind.execute(statement)


def _contributor_identity_key(last_name: str, first_name: str | None) -> str:
    def normalize(value: str | None) -> str:
        return unicodedata.normalize("NFKC", " ".join((value or "").split())).casefold()

    return f"{normalize(last_name)}\x1f{normalize(first_name)}"


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        # The items rebuild below drops and recreates a parent table; with
        # enforcement on, SQLite would cascade that drop into every child row
        # (file revisions, attachments, tag and project links).
        # SQLite only honors this pragma outside a transaction.  Alembic's
        # migration transaction is already active by the time this revision
        # runs, so use an explicit autocommit block to disable enforcement
        # before any batch rebuild starts.
        _set_sqlite_foreign_keys(bind, enabled=False)

    if _has_table(bind, "items"):
        item_columns = _columns(bind, "items")
        with op.batch_alter_table("items") as batch:
            if "lifecycle_state" not in item_columns:
                batch.add_column(
                    sa.Column(
                        "lifecycle_state",
                        sa.String(length=16),
                        nullable=False,
                        server_default="active",
                    )
                )
            if "tag_collection_version" not in item_columns:
                batch.add_column(
                    sa.Column(
                        "tag_collection_version", sa.Integer(), nullable=False, server_default="1"
                    )
                )
            if "lifecycle_fence" not in item_columns:
                batch.add_column(
                    sa.Column("lifecycle_fence", sa.Integer(), nullable=False, server_default="1")
                )
            if "aggregate_sequence" not in item_columns:
                batch.add_column(
                    sa.Column(
                        "aggregate_sequence", sa.Integer(), nullable=False, server_default="1"
                    )
                )
            if "recommendation_sequence" not in item_columns:
                batch.add_column(
                    sa.Column(
                        "recommendation_sequence",
                        sa.Integer(),
                        nullable=False,
                        server_default="1",
                    )
                )
            if "create_operation_id" not in item_columns:
                batch.add_column(
                    sa.Column("create_operation_id", sa.String(length=255), nullable=True)
                )
            checks = {
                check.get("name") for check in sa.inspect(bind).get_check_constraints("items")
            }
            if "ck_items_lifecycle_state" not in checks:
                batch.create_check_constraint(
                    "ck_items_lifecycle_state", "lifecycle_state IN ('active', 'deleting')"
                )
            uniques = {
                constraint.get("name")
                for constraint in sa.inspect(bind).get_unique_constraints("items")
            }
            if "uq_items_owner_create_operation" not in uniques:
                batch.create_unique_constraint(
                    "uq_items_owner_create_operation", ["created_by", "create_operation_id"]
                )

    for table in ("file_revisions", "attachments"):
        if not _has_table(bind, table):
            continue
        columns = _columns(bind, table)
        with op.batch_alter_table(table) as batch:
            if "lifecycle_fence" not in columns:
                batch.add_column(sa.Column("lifecycle_fence", sa.Integer(), nullable=True))
            if "operation_id" not in columns:
                batch.add_column(sa.Column("operation_id", sa.String(length=255), nullable=True))
        index_name = f"ix_{table}_operation_id"
        if index_name not in {index["name"] for index in sa.inspect(bind).get_indexes(table)}:
            op.create_index(index_name, table, ["operation_id"])
    if _has_table(bind, "import_batches"):
        batch_columns = _columns(bind, "import_batches")
        with op.batch_alter_table("import_batches") as batch:
            # ``created_by`` is the repository-wide name for the creating user;
            # this batch predates no release, so the old name is folded here.
            if "owner_id" in batch_columns:
                batch.alter_column("owner_id", new_column_name="created_by")
            if "commit_operation_id" not in batch_columns:
                batch.add_column(
                    sa.Column("commit_operation_id", sa.String(length=255), nullable=True)
                )
            if "original_name" not in batch_columns:
                batch.add_column(sa.Column("original_name", sa.String(length=255), nullable=True))
            if "committed_item_ids" not in batch_columns:
                batch.add_column(
                    sa.Column("committed_item_ids", sa.Text(), nullable=False, server_default="[]")
                )
            checks = {
                check.get("name")
                for check in sa.inspect(bind).get_check_constraints("import_batches")
            }
            if "ck_import_batches_status" in checks:
                batch.drop_constraint("ck_import_batches_status", type_="check")
            batch.create_check_constraint(
                "ck_import_batches_status",
                "status IN ('pending', 'ready', 'committing', 'committed', 'failed', 'discarded')",
            )
        if "ix_import_batches_commit_operation_id" not in {
            index["name"] for index in sa.inspect(bind).get_indexes("import_batches")
        }:
            op.create_index(
                "ix_import_batches_commit_operation_id", "import_batches", ["commit_operation_id"]
            )

    # Upload operation identities are scoped to their owner and Item.  Keep
    # the uniqueness boundary on the concrete object tables; import commit
    # identities are intentionally replayable across batches.
    for table, name in (
        ("file_revisions", "uq_file_revisions_owner_item_operation"),
        ("attachments", "uq_attachments_owner_item_operation"),
    ):
        if not _has_table(bind, table):
            continue
        columns = _columns(bind, table)
        uniques = {
            constraint.get("name") for constraint in sa.inspect(bind).get_unique_constraints(table)
        }
        if {"created_by", "item_id", "operation_id"} <= columns and name not in uniques:
            with op.batch_alter_table(table) as batch:
                batch.create_unique_constraint(name, ["created_by", "item_id", "operation_id"])

    if _has_table(bind, "authors"):
        author_columns = _columns(bind, "authors")
        if sqlite:
            author_sql = bind.scalar(
                sa.text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'authors'")
            )
            has_old_author_unique = "uq_authors_name" in (author_sql or "")
        else:
            has_old_author_unique = "uq_authors_name" in {
                constraint.get("name")
                for constraint in sa.inspect(bind).get_unique_constraints("authors")
            }
        if has_old_author_unique:
            with op.batch_alter_table("authors") as batch:
                batch.drop_constraint("uq_authors_name", type_="unique")
        if _has_named_index(bind, "authors", "uq_authors_normalized_name"):
            op.drop_index("uq_authors_normalized_name", table_name="authors")
        if "identity_key" not in author_columns:
            with op.batch_alter_table("authors") as batch:
                batch.add_column(sa.Column("identity_key", sa.Text(), nullable=True))
            rows = bind.execute(sa.text("SELECT id, last_name, first_name FROM authors")).mappings()
            for row in rows:
                bind.execute(
                    sa.text("UPDATE authors SET identity_key = :identity_key WHERE id = :id"),
                    {
                        "id": row["id"],
                        "identity_key": _contributor_identity_key(
                            row["last_name"], row["first_name"]
                        ),
                    },
                )
            with op.batch_alter_table("authors") as batch:
                batch.alter_column("identity_key", nullable=False)
        else:
            # A partially upgraded schema may already have the column but
            # contain NULL backfill values; normalize those before enforcing
            # the current non-null model contract.
            rows = bind.execute(
                sa.text("SELECT id, last_name, first_name FROM authors WHERE identity_key IS NULL")
            ).mappings()
            for row in rows:
                bind.execute(
                    sa.text("UPDATE authors SET identity_key = :identity_key WHERE id = :id"),
                    {
                        "id": row["id"],
                        "identity_key": _contributor_identity_key(
                            row["last_name"], row["first_name"]
                        ),
                    },
                )
            with op.batch_alter_table("authors") as batch:
                batch.alter_column("identity_key", type_=sa.Text(), nullable=False)
        # Legacy databases may contain separate Author rows that collapse to
        # the same canonical identity (case, whitespace or Unicode variants).
        # Resolve those rows before adding the unique identity index.  Keep the
        # lowest UUID as the canonical row and repoint ItemAuthor links while
        # removing collisions on (item, role).
        duplicate_keys = (
            bind
            .execute(
                sa.text(
                    "SELECT identity_key FROM authors "
                    "GROUP BY identity_key HAVING COUNT(*) > 1 ORDER BY identity_key"
                )
            )
            .scalars()
            .all()
        )
        for identity_key in duplicate_keys:
            author_ids = [
                row[0]
                for row in bind.execute(
                    sa.text(
                        "SELECT id FROM authors WHERE identity_key = :identity_key ORDER BY id"
                    ),
                    {"identity_key": identity_key},
                ).all()
            ]
            canonical_id, duplicate_ids = author_ids[0], author_ids[1:]
            for duplicate_id in duplicate_ids:
                links = bind.execute(
                    sa.text(
                        "SELECT id, item_id, role, position, is_corresponding FROM item_authors "
                        "WHERE author_id = :author_id ORDER BY id"
                    ),
                    {"author_id": duplicate_id},
                ).all()
                for link_id, item_id, role, position, is_corresponding in links:
                    existing_link = bind.execute(
                        sa.text(
                            "SELECT id, position, is_corresponding FROM item_authors "
                            "WHERE item_id = :item_id AND author_id = :author_id AND role = :role"
                        ),
                        {"item_id": item_id, "author_id": canonical_id, "role": role},
                    ).first()
                    if existing_link is None:
                        bind.execute(
                            sa.text(
                                "UPDATE item_authors SET author_id = :author_id WHERE id = :id"
                            ),
                            {"author_id": canonical_id, "id": link_id},
                        )
                    else:
                        existing_id, existing_position, existing_corresponding = existing_link
                        bind.execute(
                            sa.text(
                                "UPDATE item_authors SET position = :position, "
                                "is_corresponding = :is_corresponding WHERE id = :id"
                            ),
                            {
                                "id": existing_id,
                                "position": min(existing_position, position),
                                "is_corresponding": bool(
                                    existing_corresponding or is_corresponding
                                ),
                            },
                        )
                        bind.execute(
                            sa.text("DELETE FROM item_authors WHERE id = :id"),
                            {"id": link_id},
                        )
                bind.execute(sa.text("DELETE FROM authors WHERE id = :id"), {"id": duplicate_id})
        if not _has_named_index(bind, "authors", "uq_authors_identity_key"):
            op.create_index(
                "uq_authors_identity_key",
                "authors",
                ["identity_key"],
                unique=True,
            )

    # Server defaults are useful while backfilling old rows but are not part of
    # the application model. PostgreSQL can remove them without a table rebuild;
    # SQLite keeps them to avoid another expensive rebuild.
    if not sqlite:
        for table, names in {
            "items": (
                "lifecycle_state",
                "tag_collection_version",
                "lifecycle_fence",
                "aggregate_sequence",
                "recommendation_sequence",
            ),
            "import_batches": ("committed_item_ids",),
        }.items():
            if _has_table(bind, table):
                for name in names:
                    op.alter_column(table, name, server_default=None)

    if _has_table(bind, "item_tag_recommendations"):
        rec_columns = _columns(bind, "item_tag_recommendations")
        with op.batch_alter_table("item_tag_recommendations") as batch:
            if "source_sequence" not in rec_columns:
                batch.add_column(
                    sa.Column("source_sequence", sa.Integer(), nullable=False, server_default="1")
                )
        if not sqlite:
            op.alter_column("item_tag_recommendations", "source_sequence", server_default=None)

    if _has_table(bind, "users") and not _has_table(bind, "item_create_tombstones"):
        op.create_table(
            "item_create_tombstones",
            sa.Column("created_by", sa.String(length=36), nullable=False),
            sa.Column("operation_id", sa.String(length=255), nullable=False),
            sa.Column("item_id", sa.String(length=36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("created_by", "operation_id"),
        )

    if not _has_table(bind, "search_projection_state"):
        op.create_table(
            "search_projection_state",
            sa.Column("item_id", sa.String(length=36), nullable=False),
            sa.Column("requested_generation", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("item_id"),
        )
    if _has_table(bind, "items"):
        bind.execute(
            sa.text(
                "INSERT INTO search_projection_state(item_id, requested_generation, created_at) "
                "SELECT id, COALESCE(aggregate_sequence, 1), CURRENT_TIMESTAMP FROM items "
                "WHERE id NOT IN (SELECT item_id FROM search_projection_state)"
            )
        )
    if sqlite:
        # FTS5 virtual tables cannot be altered. Library Search is a derived
        # projection, so replace its schema while carrying forward rows already
        # indexed by the previous schema. Existing rows have no source token;
        # the migration backfill gives them the initial sequence used for
        # existing Items, allowing the next write to replace them normally.
        search_backup = "_item_search_0029_backup"
        if _has_table(bind, "item_search"):
            bind.execute(
                sa.text(
                    f"CREATE TABLE {search_backup} (item_id VARCHAR(36) NOT NULL, content TEXT)"
                )
            )
            bind.execute(
                sa.text(
                    f"INSERT INTO {search_backup} (item_id, content) "
                    "SELECT item_id, content FROM item_search"
                )
            )
            op.drop_table("item_search")
        op.execute(
            """
            CREATE VIRTUAL TABLE item_search USING fts5(
                item_id UNINDEXED,
                content,
                source_sequence UNINDEXED,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        if _has_table(bind, search_backup):
            bind.execute(
                sa.text(
                    f"INSERT INTO item_search (item_id, content, source_sequence) "
                    f"SELECT item_id, content, 1 FROM {search_backup}"
                )
            )
            bind.execute(sa.text(f"DROP TABLE {search_backup}"))
    else:
        op.add_column(
            "item_search",
            sa.Column("source_sequence", sa.Integer(), nullable=False, server_default="0"),
        )
        op.alter_column("item_search", "source_sequence", server_default=None)
    if sqlite:
        # Re-enable enforcement outside the migration transaction; otherwise
        # SQLite silently ignores the pragma and leaves the connection with
        # foreign-key checks disabled for subsequent work.
        _set_sqlite_foreign_keys(bind, enabled=True)


def downgrade() -> None:
    raise RuntimeError("0029_concurrency_fences is forward-only")
