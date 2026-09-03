"""Keep only transient Item Tag Recommendation generation state.

Revision ID: 0020_transient_tag_recommendations
Revises: 0019_dbos_workflows_and_uuid_objects
"""

import sqlalchemy as sa
from alembic import op

revision = "0020_transient_tag_recommendations"
down_revision = "0019_dbos_workflows_and_uuid_objects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_tag_recommendations")}
    indexes = {index["name"] for index in inspector.get_indexes("item_tag_recommendations")}
    with op.batch_alter_table("item_tag_recommendations") as batch:
        if "ix_item_tag_recommendations_input_fingerprint" in indexes:
            batch.drop_index("ix_item_tag_recommendations_input_fingerprint")
        for name in ("input_fingerprint", "engine", "engine_version", "model_fingerprint"):
            if name in columns:
                batch.drop_column(name)


def downgrade() -> None:
    raise RuntimeError("transient Tag Recommendation migration is intentionally irreversible")
