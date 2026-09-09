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


def test_search_projection_schema_is_owned_by_migrations(tmp_path: Path):
    database = tmp_path / "search-schema.db"
    database_url = f"sqlite:///{database}"
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url
    script = """
from alembic import command
from alembic.config import Config

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "head")
"""
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    engine = create_engine(database_url)
    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(item_search)")}
    engine.dispose()

    assert columns == {"item_id", "content", "source_sequence"}


def test_concurrency_migration_preserves_existing_sqlite_search_rows(tmp_path: Path):
    database = tmp_path / "search-backfill.db"
    database_url = f"sqlite:///{database}"
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url
    script = """
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

config = Config()
config.set_main_option("script_location", "migrations")
command.upgrade(config, "0028_project_management")
engine = create_engine(__import__("os").environ["QUIREBASE_DATABASE_URL"])
with engine.begin() as connection:
    connection.execute(
        text("INSERT INTO item_search(item_id, content) VALUES ('existing-item', 'legacy content')")
    )
engine.dispose()
command.upgrade(config, "head")
engine = create_engine(__import__("os").environ["QUIREBASE_DATABASE_URL"])
with engine.connect() as connection:
    row = connection.execute(
        text("SELECT item_id, content, source_sequence FROM item_search")
    ).one()
print(row.item_id, row.content, row.source_sequence)
engine.dispose()
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.stdout.strip() == "existing-item legacy content 1"


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
        connection.execute(text("INSERT INTO project_members VALUES ('project', 'user', 'owner')"))
        connection.execute(text("INSERT INTO project_items VALUES ('project', 'item')"))
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
                "SELECT state, updated_at, visibility, description "
                "FROM projects WHERE id = 'project'"
            )
        ).one()
        membership_count = connection.scalar(text("SELECT count(*) FROM project_members"))
        assignment_count = connection.scalar(text("SELECT count(*) FROM project_items"))
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).all()
    engine.dispose()

    assert {"state", "updated_at", "visibility", "description"} <= columns
    assert project.state == "active"
    assert project.updated_at is not None
    assert project.visibility == "private"
    assert project.description == ""
    assert membership_count == 1
    assert assignment_count == 1
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


def test_concurrency_fences_migration_preserves_item_children_through_upgrade_and_downgrade(
    tmp_path: Path,
):
    """0029 rebuilds the parent items table: children must survive upgrade and
    the downgrade must drop its indexes before their columns."""
    database = tmp_path / "concurrency-fences.db"
    database_url = f"sqlite:///{database}"
    environment = os.environ.copy()
    environment["QUIREBASE_DATABASE_URL"] = database_url

    def run_alembic(target: str) -> None:
        script = f"""
from alembic import command
from alembic.config import Config

config = Config()
config.set_main_option("script_location", "migrations")
command.{target}
"""
        subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

    run_alembic("upgrade(config, '0028_project_management')")

    # Replace the items table with the pre-0029 shape so the batch below
    # cannot skip its rebuild: a fresh database already carries the new
    # columns because migration 0001 builds from the current models.
    engine = create_engine(database_url)
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(
            text(
                """
                CREATE TABLE items_legacy (
                    id VARCHAR(36) NOT NULL PRIMARY KEY,
                    title TEXT NOT NULL,
                    abstract TEXT,
                    publication_date VARCHAR(32),
                    publication_title TEXT,
                    volume VARCHAR(100),
                    issue VARCHAR(100),
                    pages VARCHAR(100),
                    affiliation TEXT,
                    publisher TEXT,
                    place_published VARCHAR(255),
                    journal_abbreviation TEXT,
                    doi VARCHAR(500),
                    identifiers TEXT,
                    reference_type VARCHAR(40),
                    authors TEXT,
                    editors TEXT,
                    bibtex_id VARCHAR(255),
                    bibtex_type VARCHAR(40),
                    urls TEXT,
                    keywords TEXT,
                    custom_fields TEXT,
                    created_by VARCHAR(36) NOT NULL REFERENCES users (id),
                    updated_by VARCHAR(36) REFERENCES users (id),
                    version INTEGER NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )
        connection.execute(text("DROP TABLE items"))
        connection.execute(text("ALTER TABLE items_legacy RENAME TO items"))
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
                "VALUES ('item', 'Child carrier', 'user', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO file_revisions (id, item_id, object_key, size, mime_type, "
                "original_name, processing_state, created_by, created_at) "
                "VALUES ('revision', 'item', 'aa/bb/doc.pdf', 10, 'application/pdf', "
                "'doc.pdf', 'ready', 'user', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO attachments (id, item_id, object_key, size, mime_type, "
                "original_name, created_by, created_at) "
                "VALUES ('attachment', 'item', 'aa/bb/data.bin', 10, 'application/octet-stream', "
                "'data.bin', 'user', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO tags (id, name, created_by, created_at) "
                "VALUES ('tag', 'kept', 'user', CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO item_tags VALUES ('item', 'tag')"))
        connection.execute(
            text(
                "INSERT INTO projects (id, name, description, state, visibility, created_by, created_at, updated_at) "
                "VALUES ('project', 'Carrier project', '', 'active', 'private', 'user', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(text("INSERT INTO project_members VALUES ('project', 'user', 'owner')"))
        connection.execute(text("INSERT INTO project_items VALUES ('project', 'item')"))
    engine.dispose()

    run_alembic("upgrade(config, 'head')")
    run_alembic("downgrade(config, '0028_project_management')")

    engine = create_engine(database_url)
    with engine.begin() as connection:
        children = {
            name: connection.scalar(text(f"SELECT COUNT(*) FROM {name} WHERE item_id = 'item'"))
            for name in ("file_revisions", "attachments", "item_tags", "project_items")
        }
        batch_columns = {
            row[1] for row in connection.exec_driver_sql("PRAGMA table_info(import_batches)")
        }
    engine.dispose()
    assert children == {
        "file_revisions": 1,
        "attachments": 1,
        "item_tags": 1,
        "project_items": 1,
    }
    assert "owner_id" in batch_columns and "created_by" not in batch_columns
