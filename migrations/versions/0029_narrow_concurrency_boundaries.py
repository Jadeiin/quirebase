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
            # Preserve the effective owner from the legacy membership table.
            # Older revisions allowed multiple owner memberships and did not
            # update ``created_by`` during ownership transfer, so deriving the
            # new root owner from ``created_by`` would silently revert valid
            # transfers.  Pick a deterministic owner, demote any additional
            # legacy owners, and repair projects that had no owner row.
            bind.execute(
                sa.text(
                    """
                    UPDATE projects
                    SET owner_id = COALESCE(
                        (
                            SELECT MIN(pm.user_id)
                            FROM project_members pm
                            WHERE pm.project_id = projects.id AND pm.role = 'owner'
                        ),
                        created_by
                    )
                    WHERE owner_id IS NULL
                    """
                )
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE project_members
                    SET role = 'editor'
                    WHERE role = 'owner'
                      AND user_id <> (
                          SELECT p.owner_id FROM projects p WHERE p.id = project_members.project_id
                      )
                    """
                )
            )
            bind.execute(
                sa.text(
                    """
                    UPDATE project_members
                    SET role = 'owner'
                    WHERE user_id = (
                        SELECT p.owner_id FROM projects p WHERE p.id = project_members.project_id
                    )
                    """
                )
            )
            bind.execute(
                sa.text(
                    """
                    INSERT INTO project_members(project_id, user_id, role)
                    SELECT p.id, p.owner_id, 'owner'
                    FROM projects p
                    WHERE NOT EXISTS (
                        SELECT 1 FROM project_members pm
                        WHERE pm.project_id = p.id AND pm.user_id = p.owner_id
                    )
                    """
                )
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

    # The legacy Item projection mixed bibliographic metadata with PDF text, Tag names and
    # Project names. Rebuild both projections at the schema boundary so upgraded databases use
    # the same split as fresh writes before the application starts serving Search.
    if inspector.has_table("item_search") and sa.inspect(bind).has_table("revision_search"):
        if bind.dialect.name == "postgresql":
            op.execute("DELETE FROM item_search")
            op.execute(
                """
                INSERT INTO item_search(item_id, document)
                SELECT id, to_tsvector(
                    'simple',
                    concat_ws(
                        ' ', title, abstract, authors, editors, keywords,
                        custom_fields, identifiers
                    )
                )
                FROM items
                """
            )
            op.execute("DELETE FROM revision_search")
            op.execute(
                """
                INSERT INTO revision_search(revision_id, item_id, document)
                SELECT id, item_id, to_tsvector('simple', full_text)
                FROM file_revisions
                WHERE full_text IS NOT NULL AND full_text <> ''
                """
            )
        else:
            op.execute("DELETE FROM item_search")
            op.execute(
                """
                INSERT INTO item_search(item_id, content)
                SELECT id,
                       COALESCE(title, '') || char(10) ||
                       COALESCE(abstract, '') || char(10) ||
                       COALESCE(authors, '') || char(10) ||
                       COALESCE(editors, '') || char(10) ||
                       COALESCE(keywords, '') || char(10) ||
                       COALESCE(custom_fields, '') || char(10) ||
                       COALESCE(identifiers, '')
                FROM items
                """
            )
            op.execute("DELETE FROM revision_search")
            op.execute(
                """
                INSERT INTO revision_search(revision_id, item_id, content)
                SELECT id, item_id, full_text
                FROM file_revisions
                WHERE full_text IS NOT NULL AND full_text <> ''
                """
            )


def downgrade() -> None:
    raise NotImplementedError("forward-only alpha schema")
