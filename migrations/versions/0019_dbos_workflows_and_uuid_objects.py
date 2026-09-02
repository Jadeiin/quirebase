"""replace jobs with DBOS workflows and add durable object identities

Revision ID: 0019_dbos_workflows_and_uuid_objects
Revises: 0018_attachment_roles
"""

import sqlalchemy as sa
from alembic import op

revision = "0019_dbos_workflows_and_uuid_objects"
down_revision = "0018_attachment_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    recommendation_columns = {
        column["name"] for column in inspector.get_columns("item_tag_recommendations")
    }
    recommendation_indexes = {
        index["name"] for index in inspector.get_indexes("item_tag_recommendations")
    }
    foreign_keys = inspector.get_foreign_keys("item_tag_recommendations")
    with op.batch_alter_table(
        "item_tag_recommendations",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        if "workflow_id" not in recommendation_columns:
            batch.add_column(sa.Column("workflow_id", sa.String(length=255), nullable=True))
        if "ix_item_tag_recommendations_workflow_id" not in recommendation_indexes:
            batch.create_index("ix_item_tag_recommendations_workflow_id", ["workflow_id"])
        if "job_id" in recommendation_columns:
            job_foreign_key = next(
                (key for key in foreign_keys if key.get("constrained_columns") == ["job_id"]),
                None,
            )
            if job_foreign_key is not None:
                batch.drop_constraint(
                    job_foreign_key.get("name") or "fk_item_tag_recommendations_job_id_jobs",
                    type_="foreignkey",
                )
            batch.drop_index("ix_item_tag_recommendations_job_id")
            batch.drop_column("job_id")
    revision_columns = {column["name"] for column in inspector.get_columns("file_revisions")}
    revision_indexes = {index["name"] for index in inspector.get_indexes("file_revisions")}
    with op.batch_alter_table("file_revisions") as batch:
        if "thumbnail_object_key" not in revision_columns:
            batch.add_column(
                sa.Column("thumbnail_object_key", sa.String(length=200), nullable=True)
            )
        if "ix_file_revisions_thumbnail_object_key" not in revision_indexes:
            batch.create_index("ix_file_revisions_thumbnail_object_key", ["thumbnail_object_key"])
        if "sha256" in revision_columns:
            if "ix_file_revisions_sha256" in revision_indexes:
                batch.drop_index("ix_file_revisions_sha256")
            batch.drop_column("sha256")
    attachment_columns = {column["name"] for column in inspector.get_columns("attachments")}
    attachment_indexes = {index["name"] for index in inspector.get_indexes("attachments")}
    with op.batch_alter_table("attachments") as batch:
        if "sha256" in attachment_columns:
            if "ix_attachments_sha256" in attachment_indexes:
                batch.drop_index("ix_attachments_sha256")
            batch.drop_column("sha256")
    if inspector.has_table("jobs"):
        op.drop_table("jobs")


def downgrade() -> None:
    raise RuntimeError("DBOS workflow migration is intentionally irreversible")
