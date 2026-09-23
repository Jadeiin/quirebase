from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
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
    "item_attachments",
    "item_file_revisions",
    "item_identifiers",
    "item_reads",
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
    "project_item_tags",
    "personal_item_tags",
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


def test_migration_revisions_are_single_head_and_fit_the_version_column():
    config = Config()
    config.set_main_option("script_location", "migrations")
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    assert revisions
    assert len(script.get_heads()) == 1
    for revision in revisions:
        assert len(revision.revision) <= 32, revision.revision


def test_alembic_imports_the_mapping_module_without_a_package_facade():
    source = Path("migrations/env.py").read_text(encoding="utf-8")
    assert "import quirebase.models" in source
    assert "from quirebase import models" not in source
