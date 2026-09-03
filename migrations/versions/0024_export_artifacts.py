"""Persist annotation export artifact lifetimes.

Revision ID: 0024_export_artifacts
Revises: 0023_import_batch_status_constraint
"""

import sqlalchemy as sa
from alembic import op

revision = "0024_export_artifacts"
down_revision = "0023_import_batch_status_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("export_artifacts"):
        op.create_table(
            "export_artifacts",
            sa.Column("workflow_id", sa.String(length=255), nullable=False),
            sa.Column("object_key", sa.String(length=500), nullable=False),
            sa.Column("filename", sa.String(length=255), nullable=False),
            sa.Column("size", sa.Integer(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("workflow_id"),
            sa.UniqueConstraint("object_key"),
        )
        op.create_index(
            op.f("ix_export_artifacts_expires_at"),
            "export_artifacts",
            ["expires_at"],
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_export_artifacts_expires_at"), table_name="export_artifacts")
    op.drop_table("export_artifacts")
