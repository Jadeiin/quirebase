"""Persist asynchronous Item Tag recommendations."""

import sqlalchemy as sa
from alembic import op

revision = "0016_item_tag_recommendations"
down_revision = "0015_annotation_underline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("item_tag_recommendations"):
        return
    op.create_table(
        "item_tag_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("item_id", sa.String(length=36), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generation_token", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("engine_version", sa.String(length=64), nullable=False),
        sa.Column("model_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("single_words", sa.Text(), nullable=True),
        sa.Column("phrases", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("generation_token >= 1", name="ck_item_tag_recommendations_token"),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"], ondelete="CASCADE"),
        *(
            [sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL")]
            if sa.inspect(op.get_bind()).has_table("jobs")
            else []
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id"),
    )
    op.create_index(
        op.f("ix_item_tag_recommendations_input_fingerprint"),
        "item_tag_recommendations",
        ["input_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_item_tag_recommendations_item_id"),
        "item_tag_recommendations",
        ["item_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_item_tag_recommendations_job_id"),
        "item_tag_recommendations",
        ["job_id"],
        unique=False,
    )


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("item_tag_recommendations"):
        return
    op.drop_index(
        op.f("ix_item_tag_recommendations_job_id"),
        table_name="item_tag_recommendations",
    )
    op.drop_index(
        op.f("ix_item_tag_recommendations_item_id"),
        table_name="item_tag_recommendations",
    )
    op.drop_index(
        op.f("ix_item_tag_recommendations_input_fingerprint"),
        table_name="item_tag_recommendations",
    )
    op.drop_table("item_tag_recommendations")
