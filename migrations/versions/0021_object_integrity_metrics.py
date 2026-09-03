"""Persist thumbnail sizes and Object Store integrity scan results.

Revision ID: 0021_object_integrity_metrics
Revises: 0020_transient_tag_recommendations
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_object_integrity_metrics"
down_revision = "0020_transient_tag_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    revision_columns = {column["name"] for column in inspector.get_columns("file_revisions")}
    if "thumbnail_size" not in revision_columns:
        with op.batch_alter_table("file_revisions") as batch:
            batch.add_column(sa.Column("thumbnail_size", sa.Integer(), nullable=True))
    if not inspector.has_table("object_integrity_scans"):
        op.create_table(
            "object_integrity_scans",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("missing_count", sa.Integer(), nullable=False),
            sa.Column("mismatch_count", sa.Integer(), nullable=False),
            sa.Column("errors", sa.Text(), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_object_integrity_scans_checked_at"),
            "object_integrity_scans",
            ["checked_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_object_integrity_scans_checked_at"),
        table_name="object_integrity_scans",
    )
    op.drop_table("object_integrity_scans")
    with op.batch_alter_table("file_revisions") as batch:
        batch.drop_column("thumbnail_size")
