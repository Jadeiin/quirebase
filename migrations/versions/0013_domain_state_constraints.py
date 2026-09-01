"""Add constraints for closed domain lifecycle states."""

import sqlalchemy as sa
from alembic import op

revision = "0013_domain_state_constraints"
down_revision = "0012_rich_metadata_authors_and_uids"
branch_labels = None
depends_on = None

CONSTRAINTS = {
    "project_members": {
        "ck_project_members_role": "role IN ('owner', 'editor', 'viewer')",
    },
    "file_revisions": {
        "ck_file_revisions_processing_state": "processing_state IN ('pending', 'ready')",
    },
    "pdf_annotations": {
        "ck_pdf_annotations_kind": "kind IN ('highlight', 'note')",
        "ck_pdf_annotations_scope": "scope IN ('private', 'project')",
        "ck_pdf_annotations_project_scope": (
            "(scope = 'private' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)"
        ),
    },
    "jobs": {
        "ck_jobs_kind_shape": "length(kind) BETWEEN 1 AND 40",
        "ck_jobs_state": "state IN ('pending', 'running', 'succeeded', 'failed')",
    },
}


def constraint_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table_name):
        return set()
    return {
        constraint["name"]
        for constraint in inspector.get_check_constraints(table_name)
        if constraint.get("name")
    }


def upgrade() -> None:
    for table_name, constraints in CONSTRAINTS.items():
        if not sa.inspect(op.get_bind()).has_table(table_name):
            continue
        existing = constraint_names(table_name)
        missing = {
            name: condition for name, condition in constraints.items() if name not in existing
        }
        if not missing:
            continue
        with op.batch_alter_table(table_name) as batch:
            for name, condition in missing.items():
                batch.create_check_constraint(name, condition)


def downgrade() -> None:
    for table_name, constraints in reversed(CONSTRAINTS.items()):
        if not sa.inspect(op.get_bind()).has_table(table_name):
            continue
        existing = constraint_names(table_name)
        removable = [name for name in constraints if name in existing]
        if not removable:
            continue
        with op.batch_alter_table(table_name) as batch:
            for name in removable:
                batch.drop_constraint(name, type_="check")
