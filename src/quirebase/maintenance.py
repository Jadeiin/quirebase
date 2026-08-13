from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import select

from .config import get_settings
from .models import Attachment, FileRevision
from .storage import LocalObjectStore

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("not a SQLite database URL")
    return Path(database_url.removeprefix("sqlite:///"))


def create_backup(destination: Path) -> Path:
    settings = get_settings()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        if settings.database_url.startswith("sqlite:///"):
            source = sqlite_path(settings.database_url)
            with (
                sqlite3.connect(source) as source_db,
                sqlite3.connect(root / "database.sqlite3") as target,
            ):
                source_db.backup(target)
            database_file = "database.sqlite3"
            database_kind = "sqlite"
        else:
            executable = shutil.which("pg_dump")
            if executable is None:
                raise RuntimeError("pg_dump is required for PostgreSQL backups")
            subprocess.run(
                [
                    executable,
                    "--format=custom",
                    "--file",
                    str(root / "database.dump"),
                    settings.database_url,
                ],
                check=True,
            )
            database_file = "database.dump"
            database_kind = "postgresql"
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database_kind": database_kind,
            "database_file": database_file,
            "database_sha256": sha256_file(root / database_file),
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(root / "manifest.json", "manifest.json")
            archive.write(root / database_file, database_file)
            if settings.object_dir.exists():
                for path in settings.object_dir.rglob("*"):
                    if path.is_file():
                        archive.write(path, Path("objects") / path.relative_to(settings.object_dir))
    return destination


def verify_backup(archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise ValueError("backup has no manifest")
        manifest = json.loads(archive.read("manifest.json"))
        database_file = manifest["database_file"]
        if database_file not in names:
            raise ValueError("backup has no database payload")
        digest = hashlib.sha256(archive.read(database_file)).hexdigest()
        if digest != manifest["database_sha256"]:
            raise ValueError("database checksum mismatch")
        if any(name.startswith("/") or ".." in Path(name).parts for name in names):
            raise ValueError("unsafe backup path")
        return manifest


def restore_backup(archive_path: Path, *, force: bool = False) -> None:
    manifest = verify_backup(archive_path)
    settings = get_settings()
    expected_kind = "sqlite" if settings.database_url.startswith("sqlite:///") else "postgresql"
    if manifest["database_kind"] != expected_kind:
        raise ValueError("backup database kind does not match configured database")
    if not force:
        raise ValueError("restore requires explicit force confirmation")
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(root)
        if expected_kind == "sqlite":
            target = sqlite_path(settings.database_url)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / manifest["database_file"], target)
        else:
            executable = shutil.which("pg_restore")
            if executable is None:
                raise RuntimeError("pg_restore is required for PostgreSQL restores")
            subprocess.run(
                [
                    executable,
                    "--clean",
                    "--if-exists",
                    "--dbname",
                    settings.database_url,
                    str(root / manifest["database_file"]),
                ],
                check=True,
            )
        restored_objects = root / "objects"
        if restored_objects.exists():
            settings.object_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(restored_objects, settings.object_dir, dirs_exist_ok=True)


def cleanup_exports() -> int:
    directory = get_settings().export_dir
    cutoff = datetime.now(UTC) - timedelta(hours=get_settings().export_ttl_hours)
    removed = 0
    if directory.exists():
        for path in directory.glob("*.pdf"):
            modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
            if modified < cutoff:
                path.unlink()
                removed += 1
    return removed


def check_objects(db: Session) -> list[str]:
    store = LocalObjectStore()
    errors = []
    for revision in db.scalars(select(FileRevision)).all():
        path = store.path(revision.object_key)
        if not path.is_file():
            errors.append(f"{revision.id}: missing object")
        elif sha256_file(path) != revision.sha256:
            errors.append(f"{revision.id}: checksum mismatch")
    for attachment in db.scalars(select(Attachment)).all():
        path = store.path(attachment.object_key)
        if not path.is_file():
            errors.append(f"{attachment.id}: missing attachment")
        elif sha256_file(path) != attachment.sha256:
            errors.append(f"{attachment.id}: attachment checksum mismatch")
    return errors
