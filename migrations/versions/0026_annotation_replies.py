"""Persist collaborative replies attached to canonical PDF annotations.

Revision ID: 0026_annotation_replies
Revises: 0025_canonical_pdf_annotations
"""

import sqlalchemy as sa
from alembic import op

revision = "0026_annotation_replies"
down_revision = "0025_canonical_pdf_annotations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("pdf_annotation_replies"):
        return
    op.create_table(
        "pdf_annotation_replies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("annotation_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["annotation_id"], ["pdf_annotations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pdf_annotation_replies_annotation_id"),
        "pdf_annotation_replies",
        ["annotation_id"],
    )
    op.create_index(
        op.f("ix_pdf_annotation_replies_author_id"),
        "pdf_annotation_replies",
        ["author_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pdf_annotation_replies_author_id"), table_name="pdf_annotation_replies"
    )
    op.drop_index(
        op.f("ix_pdf_annotation_replies_annotation_id"), table_name="pdf_annotation_replies"
    )
    op.drop_table("pdf_annotation_replies")
