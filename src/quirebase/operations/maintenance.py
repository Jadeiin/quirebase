from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from quirebase.core.config import get_settings
from quirebase.core.database import is_sqlite_database_url
from quirebase.core.storage import get_object_store, is_managed_object_key
from quirebase.core.workflows import durable_operations
from quirebase.documents import (
    delete_unreferenced_objects,
    list_expired_export_artifacts,
    protected_object_keys,
    retire_expired_export_artifacts,
)
from quirebase.models import Attachment, FileRevision, User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite+aiosqlite:///"):
        return Path(database_url.removeprefix("sqlite+aiosqlite:///"))
    if not database_url.startswith("sqlite:///"):
        raise ValueError("not a SQLite database URL")
    return Path(database_url.removeprefix("sqlite:///"))


async def create_backup(destination: Path) -> Path:
    """Create a verified backup without blocking the event loop."""
    settings = get_settings()
    if settings.object_store != "local":
        raise RuntimeError("backup and restore currently require local object storage")
    await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
    root = Path(await asyncio.to_thread(tempfile.mkdtemp))
    try:
        if is_sqlite_database_url(settings.database_url):
            source = sqlite_path(settings.database_url)
            await asyncio.to_thread(_sqlite_snapshot, source, root / "database.sqlite3")
            database_file = "database.sqlite3"
            database_kind = "sqlite"
        else:
            executable = shutil.which("pg_dump")
            if executable is None:
                raise RuntimeError("pg_dump is required for PostgreSQL backups")
            _stdout, stderr, returncode = await _run_subprocess(
                executable,
                "--format=custom",
                "--file",
                str(root / "database.dump"),
                settings.database_url,
            )
            if returncode:
                message = stderr.decode(errors="replace").strip() if stderr else ""
                raise RuntimeError(f"pg_dump failed ({returncode}): {message}")
            database_file = "database.dump"
            database_kind = "postgresql"
        await asyncio.to_thread(
            _write_backup_archive,
            destination,
            root,
            database_file,
            database_kind,
            settings.object_dir,
        )
    finally:
        await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)
    return destination


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    with (
        contextlib.closing(sqlite3.connect(source)) as source_db,
        contextlib.closing(sqlite3.connect(destination)) as target,
    ):
        source_db.backup(target)


async def _run_subprocess(*args: str) -> tuple[bytes, bytes, int]:
    """Run a maintenance subprocess and terminate it when its task is cancelled."""
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await process.communicate()
    except asyncio.CancelledError:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
        raise
    return stdout or b"", stderr or b"", process.returncode or 0


def _write_backup_archive(
    destination: Path,
    root: Path,
    database_file: str,
    database_kind: str,
    object_dir: Path,
) -> None:
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
        if object_dir.exists():
            for path in object_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, Path("objects") / path.relative_to(object_dir))


async def verify_backup(archive_path: Path) -> dict[str, Any]:
    return await asyncio.to_thread(_verify_backup, archive_path)


def _verify_backup(archive_path: Path) -> dict[str, Any]:
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


async def restore_backup(archive_path: Path, *, force: bool = False) -> None:
    manifest = await verify_backup(archive_path)
    settings = get_settings()
    if settings.object_store != "local":
        raise RuntimeError("backup and restore currently require local object storage")
    expected_kind = "sqlite" if is_sqlite_database_url(settings.database_url) else "postgresql"
    if manifest["database_kind"] != expected_kind:
        raise ValueError("backup database kind does not match configured database")
    if not force:
        raise ValueError("restore requires explicit force confirmation")
    root = Path(await asyncio.to_thread(tempfile.mkdtemp))
    try:
        await asyncio.to_thread(_extract_backup, archive_path, root)
        if expected_kind == "sqlite":
            target = sqlite_path(settings.database_url)
            await asyncio.to_thread(
                _restore_sqlite_and_objects,
                root / manifest["database_file"],
                target,
                root / "objects",
                settings.object_dir,
            )
        else:
            executable = shutil.which("pg_restore")
            if executable is None:
                raise RuntimeError("pg_restore is required for PostgreSQL restores")
            _stdout, stderr, returncode = await _run_subprocess(
                executable,
                "--clean",
                "--if-exists",
                "--dbname",
                settings.database_url,
                str(root / manifest["database_file"]),
            )
            if returncode:
                message = stderr.decode(errors="replace").strip() if stderr else ""
                raise RuntimeError(f"pg_restore failed ({returncode}): {message}")
            await asyncio.to_thread(
                _restore_objects,
                root / "objects",
                settings.object_dir,
            )
    finally:
        await asyncio.to_thread(shutil.rmtree, root, ignore_errors=True)


def _extract_backup(archive_path: Path, root: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(root)


def _restore_sqlite_and_objects(
    database_file: Path,
    target: Path,
    restored_objects: Path,
    object_dir: Path,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(database_file, target)
    _restore_objects(restored_objects, object_dir)


def _restore_objects(restored_objects: Path, object_dir: Path) -> None:
    if restored_objects.exists():
        object_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(restored_objects, object_dir, dirs_exist_ok=True)


async def cleanup_exports(db: AsyncSession | None = None, *, batch_size: int = 100) -> int:
    from quirebase.operations.settings import get_effective_setting

    ttl_hours = (
        await get_effective_setting(db, "export_ttl_hours", get_settings().export_ttl_hours)
        if db is not None
        else get_settings().export_ttl_hours
    )
    if db is not None:
        await db.rollback()
    removed = await cleanup_local_exports(ttl_hours)
    if db is None:
        return removed
    artifacts = await list_expired_export_artifacts(db, batch_size)
    if not artifacts:
        return removed
    keys = await retire_expired_export_artifacts(db, artifacts)
    await db.commit()
    return removed + len(await delete_unreferenced_objects(db, keys))


async def cleanup_local_exports(ttl_hours: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    return await asyncio.to_thread(_cleanup_exports, get_settings().export_dir, cutoff)


def _cleanup_exports(directory: Path, cutoff: datetime) -> int:
    removed = 0
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file():
                modified = datetime.fromtimestamp(path.stat().st_mtime, UTC)
                if modified < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
    return removed


async def check_objects(db: AsyncSession) -> list[str]:
    errors, _candidates, _thumbnail_sizes = await scan_objects(db)
    return errors


async def scan_objects(
    db: AsyncSession, *, retention_hours: int | None = None
) -> tuple[list[str], tuple[str, ...], dict[str, dict]]:
    """Check references and find old orphans using one Object Store listing."""
    effective_hours = retention_hours or get_settings().object_orphan_retention_hours
    cutoff = datetime.now(UTC) - timedelta(hours=effective_hours)
    revisions = (
        await db.execute(select(FileRevision.id, FileRevision.file, FileRevision.thumbnail))
    ).all()
    attachments = (
        await db.execute(
            select(
                Attachment.id,
                Attachment.file["filename"].as_string().label("object_key"),
                Attachment.file["size"].as_integer().label("size"),
            )
        )
    ).all()
    await db.rollback()
    stored = {item.key: item async for item in get_object_store().iter_prefix("")}
    protected = await protected_object_keys(db)
    errors: list[str] = []
    thumbnail_sizes: dict[str, dict] = {}
    for revision in revisions:
        item = stored.get(revision.file.path)
        if item is None:
            errors.append(f"{revision.id}: missing object")
        elif item.size != revision.file.size:
            errors.append(f"{revision.id}: size mismatch")
        descriptor = revision.thumbnail
        if descriptor is not None:
            thumbnail = stored.get(descriptor.path)
            if thumbnail is None:
                errors.append(f"{revision.id}: missing thumbnail")
            elif descriptor.size is None:
                thumbnail_sizes[str(revision.id)] = {
                    "path": descriptor.path,
                    "size": thumbnail.size,
                }
            elif thumbnail.size != descriptor.size:
                errors.append(f"{revision.id}: thumbnail size mismatch")
    for attachment in attachments:
        item = stored.get(attachment.object_key)
        if item is None:
            errors.append(f"{attachment.id}: missing attachment")
        elif item.size != attachment.size:
            errors.append(f"{attachment.id}: attachment size mismatch")
    candidates = tuple(
        item.key
        for item in stored.values()
        if is_managed_object_key(item.key)
        and item.last_modified < cutoff
        and item.key not in protected
    )
    return errors, candidates, thumbnail_sizes


async def reconcile_objects(
    db: AsyncSession, *, retention_hours: int | None = None
) -> tuple[str, ...]:
    """Delete only old, managed UUID objects that remain unreferenced on recheck."""
    _errors, candidates, _thumbnail_sizes = await scan_objects(db, retention_hours=retention_hours)
    return await delete_orphan_candidates(db, candidates)


async def delete_orphan_candidates(
    db: AsyncSession, candidates: tuple[str, ...]
) -> tuple[str, ...]:
    """Let Documents recheck the scan's candidates immediately before physical deletion."""
    return await delete_unreferenced_objects(db, candidates)


async def get_backup_artifact(db: AsyncSession, admin: User, workflow_id: str) -> tuple[Path, str]:
    from quirebase.access import SystemAction, require_system_action
    from quirebase.core.errors import ResourceNotFound

    await require_system_action(db, admin, SystemAction.backup_read)
    workflow = await durable_operations().get(workflow_id)
    if (
        workflow is None
        or workflow.name != "operations.backup"
        or workflow.state != "succeeded"
        or not isinstance(workflow.output, dict)
    ):
        raise ResourceNotFound("backup artifact not found or not ready")
    filename = workflow.output.get("filename")

    if not filename:
        raise ResourceNotFound("backup filename missing")

    backup_file = get_settings().export_dir / filename
    if not await asyncio.to_thread(backup_file.is_file):
        raise ResourceNotFound("backup artifact expired or deleted")

    return backup_file, f"quirebase_backup_{workflow.id[-8:]}.zip"
