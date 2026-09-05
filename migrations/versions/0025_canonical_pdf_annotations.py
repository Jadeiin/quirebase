"""Store one strictly canonical PDF annotation per page.

Revision ID: 0025_canonical_pdf_annotations
Revises: 0024_export_artifacts
"""

import json
from collections import defaultdict
from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "0025_canonical_pdf_annotations"
down_revision = "0024_export_artifacts"
branch_labels = None
depends_on = None

COLORS = {
    "yellow": "#FFEB33",
    "green": "#59D966",
    "blue": "#59A6FF",
    "red": "#FF5959",
}


def _datetime(value):
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def _page_box(raw_geometry: str | None, page_index: int) -> tuple[float, float, float, float]:
    geometry = json.loads(raw_geometry or "[]")
    if page_index < 0 or page_index >= len(geometry):
        raise RuntimeError("cannot migrate annotation with missing page geometry")
    left, bottom, right, top = geometry[page_index]
    return float(left), float(bottom), float(right), float(top)


def _rect(x: float, y: float, width: float, height: float) -> dict[str, float]:
    return {
        "x": max(0.0, x),
        "y": max(0.0, y),
        "width": max(0.01, width),
        "height": max(0.01, height),
    }


def _outer_rect(rects: list[dict[str, float]]) -> dict[str, float]:
    left = min(rect["x"] for rect in rects)
    bottom = min(rect["y"] for rect in rects)
    right = max(rect["x"] + rect["width"] for rect in rects)
    top = max(rect["y"] + rect["height"] for rect in rects)
    return _rect(left, bottom, right - left, top - bottom)


def _payload(record, segments: list, geometry: str | None) -> tuple[int, dict]:
    page_index = int(segments[0]["page_index"])
    left, bottom, right, top = _page_box(geometry, page_index)
    color = COLORS.get(record["color"], COLORS["yellow"])
    if record["kind"] == "note":
        raw_anchor_x = segments[0]["anchor_x"]
        raw_anchor_y = segments[0]["anchor_y"]
        anchor_x = float(left if raw_anchor_x is None else raw_anchor_x) - left
        size = min(24.0, max(0.01, right - left), max(0.01, top - bottom))
        # Legacy note anchors are top-left points; canonical rectangles use a
        # bottom-left origin, so move down by the note height.
        anchor_y = (
            float(bottom if raw_anchor_y is None else raw_anchor_y) - bottom - size
        )
        note_rect = _rect(
            min(max(anchor_x, 0.0), max(0.0, right - left - size)),
            min(max(anchor_y, 0.0), max(0.0, top - bottom - size)),
            size,
            size,
        )
        return page_index, {
            "type": "note",
            "rect": note_rect,
            "style": {
                "stroke_color": color,
                "opacity": 1.0,
                "stroke_width": 1.0,
                "dash_pattern": [],
            },
        }

    segment_rects = []
    for segment in segments:
        xs = [float(segment[f"x{index}"]) - left for index in range(1, 5)]
        ys = [float(segment[f"y{index}"]) - bottom for index in range(1, 5)]
        segment_rects.append(_rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
    return page_index, {
        "type": record["kind"],
        "rect": _outer_rect(segment_rects),
        "style": {
            "stroke_color": color,
            "opacity": 0.35 if record["kind"] == "highlight" else 0.9,
            "stroke_width": 1.0,
            "dash_pattern": [],
        },
        "segment_rects": segment_rects,
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("pdf_annotation_segments"):
        columns = {column["name"] for column in inspector.get_columns("pdf_annotations")}
        if {"page_index", "payload"}.issubset(columns):
            with op.batch_alter_table("pdf_annotations") as batch:
                batch.drop_constraint("ck_pdf_annotations_kind", type_="check")
                batch.create_check_constraint(
                    "ck_pdf_annotations_kind",
                    "kind IN ('highlight', 'underline', 'strikeout', 'note', 'free_text', "
                    "'ink', 'rectangle', 'ellipse', 'line', 'arrow')",
                )
            return
        raise RuntimeError("cannot identify the PDF annotation schema to migrate")
    annotations = list(
        bind.execute(sa.text("SELECT * FROM pdf_annotations ORDER BY id")).mappings()
    )
    segment_rows = list(
        bind.execute(
            sa.text(
                "SELECT * FROM pdf_annotation_segments ORDER BY annotation_id, page_index, ordinal"
            )
        ).mappings()
    )
    geometries = dict(bind.execute(sa.text("SELECT id, page_geometry FROM file_revisions")).all())
    segments_by_annotation_page = defaultdict(lambda: defaultdict(list))
    for segment in segment_rows:
        segments_by_annotation_page[segment["annotation_id"]][segment["page_index"]].append(segment)

    op.create_table(
        "pdf_annotations_v2",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("file_revision_id", sa.String(length=36), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("selected_text", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('highlight', 'underline', 'strikeout', 'note', 'free_text', "
            "'ink', 'rectangle', 'ellipse', 'line', 'arrow')",
            name="ck_pdf_annotations_kind",
        ),
        sa.CheckConstraint("scope IN ('private', 'project')", name="ck_pdf_annotations_scope"),
        sa.CheckConstraint(
            "(scope = 'private' AND project_id IS NULL) OR "
            "(scope = 'project' AND project_id IS NOT NULL)",
            name="ck_pdf_annotations_project_scope",
        ),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["file_revision_id"], ["file_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_pdf_annotations_v2"),
    )

    output = []
    for record in annotations:
        page_groups = segments_by_annotation_page.get(record["id"], {})
        if not page_groups:
            raise RuntimeError(f"annotation {record['id']} has no geometry to migrate")
        for position, page_index in enumerate(sorted(page_groups)):
            migrated_page, payload = _payload(
                record, page_groups[page_index], geometries.get(record["file_revision_id"])
            )
            output.append({
                "id": record["id"] if position == 0 else str(uuid4()),
                "file_revision_id": record["file_revision_id"],
                "page_index": migrated_page,
                "author_id": record["author_id"],
                "kind": record["kind"],
                "scope": record["scope"],
                "project_id": record["project_id"],
                "body": record["body"],
                "selected_text": record["selected_text"],
                "payload": payload,
                "version": record["version"],
                "created_at": _datetime(record["created_at"]),
                "updated_at": _datetime(record["updated_at"]),
                "deleted_at": _datetime(record["deleted_at"]),
            })

    table = sa.table(
        "pdf_annotations_v2",
        sa.column("id", sa.String()),
        sa.column("file_revision_id", sa.String()),
        sa.column("page_index", sa.Integer()),
        sa.column("author_id", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("scope", sa.String()),
        sa.column("project_id", sa.String()),
        sa.column("body", sa.Text()),
        sa.column("selected_text", sa.Text()),
        sa.column("payload", sa.JSON()),
        sa.column("version", sa.Integer()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("deleted_at", sa.DateTime(timezone=True)),
    )
    if output:
        op.bulk_insert(table, output)
    migrated_count = bind.scalar(sa.text("SELECT count(*) FROM pdf_annotations_v2"))
    if migrated_count != len(output):
        raise RuntimeError("canonical annotation migration count mismatch")

    op.drop_table("pdf_annotation_segments")
    op.drop_table("pdf_annotations")
    op.rename_table("pdf_annotations_v2", "pdf_annotations")
    op.create_index(
        op.f("ix_pdf_annotations_file_revision_id"), "pdf_annotations", ["file_revision_id"]
    )
    op.create_index(op.f("ix_pdf_annotations_author_id"), "pdf_annotations", ["author_id"])
    op.create_index(op.f("ix_pdf_annotations_project_id"), "pdf_annotations", ["project_id"])


def downgrade() -> None:
    raise RuntimeError(
        "0025 is a destructive alpha migration; restore the pre-upgrade database to roll back"
    )
