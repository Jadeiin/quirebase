"""Add Project lifecycle, visibility, and description.

Revision ID: 0028_project_management
Revises: 0027_annotation_object_identity
"""

import sqlalchemy as sa
from alembic import op

revision = "0028_project_management"
down_revision = "0027_annotation_object_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))

    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("projects")}
    if "state" not in columns:
        op.add_column(
            "projects",
            sa.Column("state", sa.String(length=8), nullable=False, server_default="active"),
        )
    if "updated_at" not in columns:
        op.add_column(
            "projects",
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )
        source = "created_at" if "created_at" in columns else "CURRENT_TIMESTAMP"
        op.execute(sa.text(f"UPDATE projects SET updated_at = {source} WHERE updated_at IS NULL"))
    if "visibility" not in columns:
        op.add_column(
            "projects",
            sa.Column(
                "visibility",
                sa.String(length=7),
                nullable=False,
                server_default="private",
            ),
        )
    if "description" not in columns:
        op.add_column(
            "projects",
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
        )

    inspector = sa.inspect(bind)
    columns = {column["name"]: column for column in inspector.get_columns("projects")}
    checks = {check.get("name") for check in inspector.get_check_constraints("projects")}
    needs_batch = (
        columns["updated_at"]["nullable"]
        or "ck_projects_state" not in checks
        or "ck_projects_visibility" not in checks
    )
    if needs_batch:
        with op.batch_alter_table("projects") as batch:
            if columns["updated_at"]["nullable"]:
                batch.alter_column("updated_at", nullable=False)
            if "ck_projects_state" not in checks:
                batch.create_check_constraint(
                    "ck_projects_state", "state IN ('active', 'archived')"
                )
            if "ck_projects_visibility" not in checks:
                batch.create_check_constraint(
                    "ck_projects_visibility", "visibility IN ('private', 'public')"
                )

    # Defaults are only needed to backfill existing rows. Avoid another SQLite
    # table rebuild solely to remove them after the constraint rebuild above.
    if not sqlite:
        for column_name in ("state", "visibility", "description"):
            op.alter_column("projects", column_name, server_default=None)
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def downgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("ck_projects_visibility", type_="check")
        batch.drop_constraint("ck_projects_state", type_="check")
        batch.drop_column("description")
        batch.drop_column("visibility")
        batch.drop_column("updated_at")
        batch.drop_column("state")
    if sqlite:
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))
