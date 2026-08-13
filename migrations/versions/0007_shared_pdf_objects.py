"""Allow multiple revisions to reference one content-addressed PDF object."""

import sqlalchemy as sa
from alembic import op

revision = "0007_shared_pdf_objects"
down_revision = "0006_attachments_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = inspector.get_unique_constraints("file_revisions")
    target = next(
        (constraint for constraint in constraints if constraint["column_names"] == ["object_key"]),
        None,
    )
    if target:
        naming = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        name = target["name"] or "uq_file_revisions_object_key"
        with op.batch_alter_table("file_revisions", naming_convention=naming) as batch:
            batch.drop_constraint(name, type_="unique")
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("file_revisions")}
    if "ix_file_revisions_object_key" not in indexes:
        op.create_index("ix_file_revisions_object_key", "file_revisions", ["object_key"])


def downgrade() -> None:
    op.drop_index("ix_file_revisions_object_key", table_name="file_revisions")
    op.create_unique_constraint("uq_file_revisions_object_key", "file_revisions", ["object_key"])
