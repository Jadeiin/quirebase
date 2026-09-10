"""Scope Import commit operation identities to their Batch."""

import sqlalchemy as sa
from alembic import op

revision = "0030_scoped_import_operations"
down_revision = "0029_concurrency_fences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("import_batches"):
        return
    names = {
        constraint.get("name")
        for constraint in sa.inspect(bind).get_unique_constraints("import_batches")
    }
    if "uq_import_batches_commit_operation_id" in names:
        with op.batch_alter_table("import_batches") as batch:
            batch.drop_constraint("uq_import_batches_commit_operation_id", type_="unique")


def downgrade() -> None:
    raise RuntimeError("0030_scoped_import_operations is forward-only")
