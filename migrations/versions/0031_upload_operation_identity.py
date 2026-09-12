"""Scope caller-provided upload operation identities per owner and Item."""

import sqlalchemy as sa
from alembic import op

revision = "0031_upload_operation_identity"
down_revision = "0030_scoped_import_operations"
branch_labels = None
depends_on = None


def _set_sqlite_foreign_keys(bind, enabled: bool) -> None:
    """Toggle SQLite FK enforcement outside the migration transaction."""

    statement = sa.text(f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}")
    context = op.get_context()
    if getattr(context, "_transaction", None) is not None:
        with context.autocommit_block():
            op.execute(statement)
        return
    if bind.in_transaction():
        # Direct revision callers may wrap the connection in an outer
        # SQLAlchemy transaction. Commit the DBAPI transaction without
        # invalidating that outer context manager before changing the pragma.
        driver = bind.connection.driver_connection
        driver.commit()
        driver.execute(str(statement))
    else:
        bind.execute(statement)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        # ``batch_alter_table`` rebuilds file_revisions. Existing
        # pdf_annotations rows reference that table, so FK enforcement must
        # be disabled while the old parent is replaced or SQLite may reject
        # the drop (or cascade-delete the annotation rows).
        _set_sqlite_foreign_keys(bind, enabled=False)
    for table, name in (
        ("file_revisions", "uq_file_revisions_owner_item_operation"),
        ("attachments", "uq_attachments_owner_item_operation"),
    ):
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        existing = {
            constraint.get("name") for constraint in inspector.get_unique_constraints(table)
        }
        if {"created_by", "item_id", "operation_id"} <= columns and name not in existing:
            with op.batch_alter_table(table) as batch:
                batch.create_unique_constraint(name, ["created_by", "item_id", "operation_id"])
    if sqlite:
        _set_sqlite_foreign_keys(bind, enabled=True)


def downgrade() -> None:
    raise RuntimeError("0031_upload_operation_identity is forward-only")
