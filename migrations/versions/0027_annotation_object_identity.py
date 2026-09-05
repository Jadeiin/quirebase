"""Give annotations and replies one atomic object-ID namespace.

Revision ID: 0027_annotation_object_identity
Revises: 0026_annotation_replies
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_annotation_object_identity"
down_revision = "0026_annotation_replies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pdf_annotation_objects"):
        op.create_table(
            "pdf_annotation_objects",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("object_type", sa.String(length=16), nullable=False),
            sa.CheckConstraint(
                "object_type IN ('annotation', 'reply')",
                name="ck_pdf_annotation_objects_type",
            ),
            sa.PrimaryKeyConstraint("id"),
        )

    collision = bind.scalar(
        sa.text(
            "SELECT a.id FROM pdf_annotations AS a "
            "JOIN pdf_annotation_replies AS r ON r.id = a.id LIMIT 1"
        )
    )
    if collision is not None:
        raise RuntimeError(f"annotation object ID is used by both a root and reply: {collision}")
    type_conflict = bind.scalar(
        sa.text(
            "SELECT o.id FROM pdf_annotation_objects AS o "
            "LEFT JOIN pdf_annotations AS a ON a.id = o.id "
            "LEFT JOIN pdf_annotation_replies AS r ON r.id = o.id "
            "WHERE (a.id IS NOT NULL AND o.object_type <> 'annotation') "
            "OR (r.id IS NOT NULL AND o.object_type <> 'reply') LIMIT 1"
        )
    )
    if type_conflict is not None:
        raise RuntimeError(f"annotation object has an inconsistent type: {type_conflict}")

    bind.execute(
        sa.text(
            "INSERT INTO pdf_annotation_objects (id, object_type) "
            "SELECT a.id, 'annotation' FROM pdf_annotations AS a "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM pdf_annotation_objects AS o WHERE o.id = a.id)"
        )
    )
    bind.execute(
        sa.text(
            "INSERT INTO pdf_annotation_objects (id, object_type) "
            "SELECT r.id, 'reply' FROM pdf_annotation_replies AS r "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM pdf_annotation_objects AS o WHERE o.id = r.id)"
        )
    )

    inspector = sa.inspect(bind)
    annotation_foreign_keys = inspector.get_foreign_keys("pdf_annotations")
    if not any(key["referred_table"] == "pdf_annotation_objects" for key in annotation_foreign_keys):
        with op.batch_alter_table("pdf_annotations") as batch:
            batch.create_foreign_key(
                "fk_pdf_annotations_object_id",
                "pdf_annotation_objects",
                ["id"],
                ["id"],
            )
    inspector = sa.inspect(bind)
    reply_foreign_keys = inspector.get_foreign_keys("pdf_annotation_replies")
    if not any(key["referred_table"] == "pdf_annotation_objects" for key in reply_foreign_keys):
        with op.batch_alter_table("pdf_annotation_replies") as batch:
            batch.create_foreign_key(
                "fk_pdf_annotation_replies_object_id",
                "pdf_annotation_objects",
                ["id"],
                ["id"],
            )


def downgrade() -> None:
    with op.batch_alter_table("pdf_annotation_replies") as batch:
        batch.drop_constraint("fk_pdf_annotation_replies_object_id", type_="foreignkey")
    with op.batch_alter_table("pdf_annotations") as batch:
        batch.drop_constraint("fk_pdf_annotations_object_id", type_="foreignkey")
    op.drop_table("pdf_annotation_objects")
