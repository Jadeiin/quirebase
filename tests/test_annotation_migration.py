from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def test_0025_splits_cross_page_annotations_and_removes_legacy_schema(tmp_path: Path):
    database = tmp_path / "annotations-0024.db"
    script = r'''
import json
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

engine = create_engine("sqlite:///" + os.environ["MIGRATION_DATABASE"])
with engine.begin() as connection:
    connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO alembic_version VALUES ('0024_export_artifacts')"))
    connection.execute(text("CREATE TABLE file_revisions (id VARCHAR(36) PRIMARY KEY, page_geometry TEXT)"))
    connection.execute(text("INSERT INTO file_revisions VALUES ('revision', '[[10,20,210,320],[0,0,200,300],[-10,-20,190,280]]')"))
    connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO users VALUES ('author')"))
    connection.execute(text("CREATE TABLE projects (id VARCHAR(36) PRIMARY KEY)"))
    connection.execute(text("INSERT INTO projects VALUES ('project')"))
    connection.execute(text("""
        CREATE TABLE pdf_annotations (
          id VARCHAR(36) PRIMARY KEY, file_revision_id VARCHAR(36) NOT NULL,
          author_id VARCHAR(36) NOT NULL, kind VARCHAR(32) NOT NULL,
          scope VARCHAR(32) NOT NULL, project_id VARCHAR(36), color VARCHAR(16) NOT NULL,
          body TEXT, selected_text TEXT, version INTEGER NOT NULL,
          created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, deleted_at DATETIME
        )
    """))
    connection.execute(text("""
        CREATE TABLE pdf_annotation_segments (
          id VARCHAR(36) PRIMARY KEY, annotation_id VARCHAR(36) NOT NULL,
          page_index INTEGER NOT NULL, ordinal INTEGER NOT NULL,
          x1 FLOAT, y1 FLOAT, x2 FLOAT, y2 FLOAT, x3 FLOAT, y3 FLOAT, x4 FLOAT, y4 FLOAT,
          anchor_x FLOAT, anchor_y FLOAT
        )
    """))
    common = "'revision','author',:kind,:scope,:project,:color,:body,:selected,:version,:created,:updated,:deleted"
    for annotation_id, kind, scope, project, color, body, selected, version, deleted in [
        ('00000000-0000-4000-8000-000000000001', 'highlight', 'private', None, 'yellow', 'H', 'Selected', 3, None),
        ('00000000-0000-4000-8000-000000000002', 'note', 'private', None, 'blue', 'N', None, 5, '2026-01-03 00:00:00'),
        ('00000000-0000-4000-8000-000000000003', 'underline', 'project', 'project', 'red', 'U', 'Under', 2, None),
        ('00000000-0000-4000-8000-000000000004', 'note', 'private', None, 'green', 'Zero', None, 1, None),
    ]:
        connection.execute(text(
            "INSERT INTO pdf_annotations VALUES (:id," + common + ")"
        ), {"id": annotation_id, "kind": kind, "scope": scope, "project": project,
            "color": color, "body": body, "selected": selected, "version": version,
            "created": "2026-01-01 00:00:00", "updated": "2026-01-02 00:00:00", "deleted": deleted})
    segments = [
        ('s1','00000000-0000-4000-8000-000000000001',0,0,20,300,80,300,20,280,80,280,None,None),
        ('s2','00000000-0000-4000-8000-000000000001',0,1,20,260,70,260,20,240,70,240,None,None),
        ('s3','00000000-0000-4000-8000-000000000001',1,2,10,100,50,100,10,80,50,80,None,None),
        ('s4','00000000-0000-4000-8000-000000000002',0,0,None,None,None,None,None,None,None,None,205,315),
        ('s5','00000000-0000-4000-8000-000000000003',0,0,30,200,90,200,30,185,90,185,None,None),
        ('s6','00000000-0000-4000-8000-000000000004',2,0,None,None,None,None,None,None,None,None,0,0),
    ]
    for row in segments:
        connection.execute(text("INSERT INTO pdf_annotation_segments VALUES (" + ",".join(f":v{i}" for i in range(14)) + ")"), {f"v{i}": value for i, value in enumerate(row)})
engine.dispose()

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "head")
engine = create_engine("sqlite:///" + os.environ["MIGRATION_DATABASE"])
with engine.connect() as connection:
    rows = connection.execute(text("SELECT id,page_index,kind,scope,project_id,body,selected_text,version,created_at,updated_at,deleted_at,payload FROM pdf_annotations ORDER BY page_index,id")).mappings().all()
    result = {
        "tables": inspect(connection).get_table_names(),
        "columns": [column["name"] for column in inspect(connection).get_columns("pdf_annotations")],
        "checks": [constraint["name"] for constraint in inspect(connection).get_check_constraints("pdf_annotations")],
        "rows": [dict(row) | {"payload": json.loads(row["payload"])} for row in rows],
    }
print(json.dumps(result, default=str))
'''
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = f"sqlite:///{database}"
    environment["MIGRATION_DATABASE"] = str(database)
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    migrated = json.loads(result.stdout)
    assert "pdf_annotation_segments" not in migrated["tables"]
    assert "color" not in migrated["columns"]
    assert {"page_index", "payload"}.issubset(migrated["columns"])
    assert set(migrated["checks"]) == {
        "ck_pdf_annotations_kind",
        "ck_pdf_annotations_project_scope",
        "ck_pdf_annotations_scope",
    }
    assert len(migrated["rows"]) == 5
    retained = next(row for row in migrated["rows"] if row["id"].endswith("0001"))
    assert retained["page_index"] == 0
    assert len(retained["payload"]["segment_rects"]) == 2
    split = [row for row in migrated["rows"] if row["kind"] == "highlight" and row != retained]
    assert len(split) == 1 and split[0]["page_index"] == 1
    note = next(row for row in migrated["rows"] if row["id"].endswith("0002"))
    assert note["version"] == 5
    assert note["deleted_at"] is not None
    assert note["payload"]["rect"] == {"x": 176.0, "y": 271.0, "width": 24.0, "height": 24.0}
    zero_anchor_note = next(row for row in migrated["rows"] if row["id"].endswith("0004"))
    assert zero_anchor_note["payload"]["rect"] == {
        "x": 10.0,
        "y": 0.0,
        "width": 24.0,
        "height": 24.0,
    }
    project = next(row for row in migrated["rows"] if row["kind"] == "underline")
    assert project["scope"] == "project" and project["project_id"] == "project"


def test_0027_rejects_existing_cross_table_object_id_collisions(tmp_path: Path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'annotation-object-collision.db'}")
    shared_id = "00000000-0000-4000-8000-000000000001"
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE pdf_annotations (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(
            text("CREATE TABLE pdf_annotation_replies (id VARCHAR(36) PRIMARY KEY)")
        )
        connection.execute(
            text("INSERT INTO pdf_annotations (id) VALUES (:id)"), {"id": shared_id}
        )
        connection.execute(
            text("INSERT INTO pdf_annotation_replies (id) VALUES (:id)"),
            {"id": shared_id},
        )
        migration_path = (
            Path(__file__).parents[1]
            / "migrations/versions/0027_annotation_object_identity.py"
        )
        spec = spec_from_file_location("annotation_object_identity_migration", migration_path)
        assert spec is not None and spec.loader is not None
        migration = module_from_spec(spec)
        spec.loader.exec_module(migration)
        monkeypatch.setattr(
            migration,
            "op",
            Operations(MigrationContext.configure(connection)),
        )

        with pytest.raises(RuntimeError, match=shared_id):
            migration.upgrade()
    engine.dispose()
