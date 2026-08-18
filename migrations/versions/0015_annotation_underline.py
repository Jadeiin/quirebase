"""Allow underline PDF annotations."""

import sqlalchemy as sa
from alembic import op

revision = "0015_annotation_underline"
down_revision = "0014_canonical_doi"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pdf_annotations") as batch:
        batch.drop_constraint("ck_pdf_annotations_kind", type_="check")
        batch.create_check_constraint(
            "ck_pdf_annotations_kind",
            "kind IN ('highlight', 'underline', 'note')",
        )


def downgrade() -> None:
    op.execute(sa.text("UPDATE pdf_annotations SET kind = 'highlight' WHERE kind = 'underline'"))
    with op.batch_alter_table("pdf_annotations") as batch:
        batch.drop_constraint("ck_pdf_annotations_kind", type_="check")
        batch.create_check_constraint(
            "ck_pdf_annotations_kind",
            "kind IN ('highlight', 'note')",
        )
