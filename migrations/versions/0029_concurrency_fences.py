"""Add aggregate lifecycle fences, idempotency keys and import commit state.

The fields in this migration deliberately live alongside the existing optimistic
``Item.version`` token. Version detects stale editor pages; lifecycle_fence,
aggregate_sequence and recommendation_sequence protect work that can finish
after the request that started it.

The migration also renames ``import_batches.owner_id`` to ``created_by`` to match
the repository-wide name for the creating user.
"""

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


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        # The items rebuild below drops and recreates a parent table; with
        # enforcement on, SQLite would cascade that drop into every child row
        # (file revisions, attachments, tag and project links).
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))

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
            uniques = {
                constraint.get("name")
                for constraint in sa.inspect(bind).get_unique_constraints("import_batches")
            }
            if "uq_import_batches_commit_operation_id" not in uniques:
                batch.create_unique_constraint(
                    "uq_import_batches_commit_operation_id", ["commit_operation_id"]
                )
        if "ix_import_batches_commit_operation_id" not in {
            index["name"] for index in sa.inspect(bind).get_indexes("import_batches")
        }:
            op.create_index(
                "ix_import_batches_commit_operation_id", "import_batches", ["commit_operation_id"]
            )

    # Server defaults are useful while backfilling old rows but are not part of
    # the application model. PostgreSQL can remove them without a table rebuild;
    # SQLite keeps them to avoid another expensive rebuild.
    if not sqlite:
        for table, names in {
            "items": (
                "lifecycle_state",
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
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        # The downgrade rebuilds the parent items table and drops indexed
        # columns; enforcement must be off for the rebuild and the indexes must
        # be dropped before their columns disappear.
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    for index_name, table in (
        ("ix_import_batches_commit_operation_id", "import_batches"),
        ("ix_file_revisions_operation_id", "file_revisions"),
        ("ix_attachments_operation_id", "attachments"),
    ):
        if _has_table(bind, table) and index_name in {
            index["name"] for index in sa.inspect(bind).get_indexes(table)
        }:
            op.drop_index(index_name, table_name=table)
    for name, table in (
        ("uq_import_batches_commit_operation_id", "import_batches"),
        ("uq_items_owner_create_operation", "items"),
    ):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="unique")
    for table in ("import_batches", "attachments", "file_revisions", "items"):
        with op.batch_alter_table(table) as batch:
            if table == "import_batches":
                batch.drop_constraint("ck_import_batches_status", type_="check")
                batch.create_check_constraint(
                    "ck_import_batches_status", "status IN ('pending', 'ready', 'failed')"
                )
                batch.drop_column("committed_item_ids")
                batch.drop_column("commit_operation_id")
                batch.drop_column("original_name")
                batch.alter_column("created_by", new_column_name="owner_id")
            elif table in ("attachments", "file_revisions"):
                batch.drop_column("operation_id")
                batch.drop_column("lifecycle_fence")
            else:
                batch.drop_constraint("ck_items_lifecycle_state", type_="check")
                batch.drop_column("create_operation_id")
                batch.drop_column("recommendation_sequence")
                batch.drop_column("aggregate_sequence")
                batch.drop_column("lifecycle_fence")
                batch.drop_column("lifecycle_state")
    with op.batch_alter_table("item_tag_recommendations") as batch:
        batch.drop_column("source_sequence")
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))
