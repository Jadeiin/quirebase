from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

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
    "pdf_annotation_segments",
    "pdf_annotations",
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
