from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

EXPECTED_TABLES = {
    "api_tokens",
    "attachments",
    "audit_events",
    "authors",
    "citation_styles",
    "discussion_messages",
    "export_artifacts",
    "file_revisions",
    "import_batches",
    "invitations",
    "item_authors",
    "item_identifiers",
    "item_reads",
    "item_tags",
    "item_tag_recommendations",
    "items",
    "login_sessions",
    "login_throttles",
    "object_integrity_scans",
    "pdf_annotations",
    "pdf_annotation_objects",
    "pdf_annotation_replies",
    "project_items",
    "project_members",
    "projects",
    "system_settings",
    "tags",
    "users",
}


def test_models_import_complete_metadata_without_web_or_business_facades():
    script = """
import json
import sys
import quirebase.models
from quirebase.core.database import Base
print(json.dumps({
    "tables": sorted(Base.metadata.tables),
    "web": any(name.startswith("quirebase.web") for name in sys.modules),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload == {"tables": sorted(EXPECTED_TABLES), "web": False}


def test_alembic_upgrades_complete_metadata_without_web(tmp_path: Path):
    database = tmp_path / "migration.db"
    script = """
import sys
from alembic import command
from alembic.config import Config

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "head")
assert not any(name.startswith("quirebase.web") for name in sys.modules)
"""
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = f"sqlite:///{database}"
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    engine = create_engine(f"sqlite:///{database}")
    tables = set(inspect(engine).get_table_names())
    engine.dispose()
    assert EXPECTED_TABLES | {"alembic_version"} <= tables


def test_project_management_migration_upgrades_existing_schema_without_losing_links(
    tmp_path: Path,
):
    database = tmp_path / "project-management.db"
    database_url = f"sqlite:///{database}"
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url
    migrate = """
from alembic import command
from alembic.config import Config

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "0027_annotation_object_identity")
"""
    subprocess.run(
        [sys.executable, "-c", migrate],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            text(
                "CREATE TABLE projects_legacy ("
                "id VARCHAR(36) NOT NULL PRIMARY KEY, "
                "name VARCHAR(240) NOT NULL, "
                "created_by VARCHAR(36) NOT NULL REFERENCES users (id), "
                "created_at DATETIME NOT NULL)"
            )
        )
        connection.execute(text("DROP TABLE projects"))
        connection.execute(text("ALTER TABLE projects_legacy RENAME TO projects"))
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, password_hash, role, active, created_at) "
                "VALUES ('user', 'owner', 'unused', 'member', 1, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO items (id, title, created_by, version, created_at, updated_at) "
                "VALUES ('item', 'Existing item', 'user', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, name, created_by, created_at) "
                "VALUES ('project', 'Existing project', 'user', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO projects "
                "(id, name, created_by, created_at) "
                "VALUES ('fallback-project', 'Fallback project', 'user', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO project_members VALUES ('project', 'user', 'owner')"))
        connection.execute(
            text("INSERT INTO project_members VALUES ('fallback-project', 'user', 'editor')")
        )
        connection.execute(text("INSERT INTO project_items VALUES ('project', 'item')"))
        connection.execute(
            text(
                "INSERT INTO file_revisions "
                "(id, item_id, object_key, thumbnail_object_key, thumbnail_size, size, mime_type, "
                "original_name, page_count, page_geometry, full_text, processing_state, created_by, "
                "created_at) VALUES "
                "('revision', 'item', 'revision.pdf', NULL, NULL, 10, 'application/pdf', "
                "'revision.pdf', 1, NULL, 'existing revision text', 'ready', 'user', "
                "CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO item_search(item_id, content) "
                "VALUES ('item', 'obsolete project tag text')"
            )
        )
    engine.dispose()

    subprocess.run(
        [sys.executable, "-c", migrate.replace("0027_annotation_object_identity", "head")],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        columns = {column["name"] for column in inspect(connection).get_columns("projects")}
        project = connection.execute(
            text(
                "SELECT state, updated_at, visibility, description, owner_id "
                "FROM projects WHERE id = 'project'"
            )
        ).one()
        fallback_owner = connection.execute(
            text(
                "SELECT p.owner_id, pm.role FROM projects p "
                "JOIN project_members pm "
                "ON pm.project_id = p.id AND pm.user_id = p.owner_id "
                "WHERE p.id = 'fallback-project'"
            )
        ).one()
        membership_count = connection.scalar(text("SELECT count(*) FROM project_members"))
        assignment_count = connection.scalar(text("SELECT count(*) FROM project_items"))
        item_search_content = connection.scalar(
            text("SELECT content FROM item_search WHERE item_id = 'item'")
        )
        revision_search_content = connection.scalar(
            text("SELECT content FROM revision_search WHERE revision_id = 'revision'")
        )
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()

    assert {"state", "updated_at", "visibility", "description"} <= columns
    assert project.state == "active"
    assert project.updated_at is not None
    assert project.visibility == "private"
    assert project.description == ""
    assert project.owner_id == "user"
    assert fallback_owner == ("user", "owner")
    assert membership_count == 2
    assert assignment_count == 1
    assert item_search_content is not None and "Existing item" in item_search_content
    assert "obsolete project tag text" not in item_search_content
    assert revision_search_content == "existing revision text"
    assert foreign_key_errors == []


def test_rich_metadata_migration_deduplicates_contributors_per_role(tmp_path: Path):
    database = tmp_path / "duplicate-contributors.db"
    script = """
import json
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from quirebase.models import Item, User

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "0011_system_settings")
engine = create_engine("sqlite:///" + __import__("os").environ["MIGRATION_DATABASE"])
with Session(engine) as db:
    user = User(username="migration-user", password_hash="hash")
    db.add(user)
    db.flush()
    item = Item(
        title="Repeated contributors",
        authors="Lovelace, Ada; Lovelace, Ada; Turing, Alan",
        editors="Hopper, Grace; Hopper, Grace",
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    item_id = item.id
engine.dispose()

command.upgrade(config, "head")
engine = create_engine("sqlite:///" + __import__("os").environ["MIGRATION_DATABASE"])
with engine.connect() as connection:
    rows = connection.execute(
        text(
            "SELECT ia.role, ia.position, a.last_name, a.first_name "
            "FROM item_authors AS ia "
            "JOIN authors AS a ON a.id = ia.author_id "
            "WHERE ia.item_id = :item_id "
            "ORDER BY ia.role, ia.position"
        ),
        {"item_id": item_id},
    ).all()
print(json.dumps([list(row) for row in rows]))
engine.dispose()
"""
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
    assert json.loads(result.stdout) == [
        ["author", 1, "Lovelace", "Ada"],
        ["author", 3, "Turing", "Alan"],
        ["editor", 1, "Hopper", "Grace"],
    ]


def test_alembic_imports_the_mapping_module_without_a_package_facade():
    source = Path("migrations/env.py").read_text(encoding="utf-8")
    assert "import quirebase.models" in source
    assert "from quirebase import models" not in source
