"""Apply the narrow concurrency schema in one forward-only cutover.

The application is alpha software and this revision is the only schema boundary
for the rewritten concurrency model.  It adds the Project owner root, durable
ImportBatch confirmation results, and the revision-owned search projection.
"""

import sqlalchemy as sa
from alembic import op

revision = "0029_narrow_concurrency_boundaries"
down_revision = "0028_project_management"
branch_labels = None
depends_on = None


def _sqlite_fk(bind: sa.Connection, enabled: bool) -> None:
    if bind.dialect.name != "sqlite":
        return
    # SQLite only honors this pragma outside an active transaction.  Alembic's
    # autocommit block commits the migration transaction before rebuilding a
    # parent table, preserving all FK children during the rebuild.
    with op.get_context().autocommit_block():
        bind.execute(sa.text(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("projects"):
        columns = {column["name"] for column in inspector.get_columns("projects")}
        if "owner_id" not in columns and "created_by" in columns:
            _sqlite_fk(bind, False)
            with op.batch_alter_table("projects") as batch:
                batch.add_column(sa.Column("owner_id", sa.String(length=36), nullable=True))
            bind.execute(
                sa.text("UPDATE projects SET owner_id = created_by WHERE owner_id IS NULL")
            )
            with op.batch_alter_table("projects") as batch:
                batch.alter_column("owner_id", nullable=False)
                batch.create_foreign_key(
                    "fk_projects_owner_id_users", "users", ["owner_id"], ["id"]
                )
                batch.create_index("ix_projects_owner_id", ["owner_id"])
            _sqlite_fk(bind, True)

    inspector = sa.inspect(bind)
    if inspector.has_table("import_batches"):
        columns = {column["name"] for column in inspector.get_columns("import_batches")}
        checks = {check.get("name") for check in inspector.get_check_constraints("import_batches")}
        _sqlite_fk(bind, False)
        with op.batch_alter_table("import_batches") as batch:
            if "committed_item_ids" not in columns:
                batch.add_column(sa.Column("committed_item_ids", sa.Text(), nullable=True))
            if "ck_import_batches_status" in checks:
                batch.drop_constraint("ck_import_batches_status", type_="check")
            batch.create_check_constraint(
                "ck_import_batches_status",
                "status IN ('pending', 'ready', 'failed', 'committed')",
            )
        _sqlite_fk(bind, True)

    if not inspector.has_table("revision_search"):
        if bind.dialect.name == "postgresql":
            op.execute(
                """
                CREATE TABLE revision_search (
                    revision_id varchar(36) PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,
                    item_id varchar(36) NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                    document tsvector NOT NULL
                )
                """
            )
            op.execute(
                "CREATE INDEX ix_revision_search_document ON revision_search USING gin(document)"
            )
        else:
            op.execute(
                """
                CREATE VIRTUAL TABLE revision_search USING fts5(
                    revision_id UNINDEXED,
                    item_id UNINDEXED,
                    content,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )


def downgrade() -> None:
    raise NotImplementedError("forward-only alpha schema")
