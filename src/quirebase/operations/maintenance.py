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
from quirebase.core.storage import get_object_store
from quirebase.models import Attachment, FileRevision, JobState, User

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


async def cleanup_exports(db: AsyncSession | None = None) -> int:
    from quirebase.operations.settings import get_effective_setting

    directory = get_settings().export_dir
    ttl_hours = (
        await get_effective_setting(db, "export_ttl_hours", get_settings().export_ttl_hours)
        if db is not None
        else get_settings().export_ttl_hours
    )
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    removed = await asyncio.to_thread(_cleanup_exports, directory, cutoff)
    store = get_object_store()
    async for item in store.iter_prefix("artifacts/annotation-exports/"):
        if item.last_modified < cutoff and await store.delete(item.key):
            removed += 1
    return removed


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
    store = get_object_store()
    revisions = list((await db.scalars(select(FileRevision))).all())
    attachments = list((await db.scalars(select(Attachment))).all())
    errors: list[str] = []
    for revision in revisions:
        if not await store.exists(revision.object_key):
            errors.append(f"{revision.id}: missing object")
        elif await _object_sha256(store, revision.object_key) != revision.sha256:
            errors.append(f"{revision.id}: checksum mismatch")
    for attachment in attachments:
        if not await store.exists(attachment.object_key):
            errors.append(f"{attachment.id}: missing attachment")
        elif await _object_sha256(store, attachment.object_key) != attachment.sha256:
            errors.append(f"{attachment.id}: attachment checksum mismatch")
    return errors


async def _object_sha256(store, key: str) -> str:
    digest = hashlib.sha256()
    response = await store.get(key)
    async for chunk in response.body:
        digest.update(chunk)
    return digest.hexdigest()


async def get_backup_artifact(db: AsyncSession, admin: User, job_id: str) -> tuple[Path, str]:
    from quirebase.core.errors import ResourceNotFound, ResourceUnavailable
    from quirebase.models import Job

    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    job = await db.get(Job, job_id)
    if (
        job is None
        or job.kind != "system.backup"
        or job.state != JobState.succeeded
        or not job.result
    ):
        raise ResourceNotFound("backup artifact not found or not ready")
    try:
        data = json.loads(job.result)
        filename = data.get("filename")
    except Exception as error:
        raise ResourceUnavailable("corrupt backup job result") from error

    if not filename:
        raise ResourceNotFound("backup filename missing")

    backup_file = get_settings().export_dir / filename
    if not await asyncio.to_thread(backup_file.is_file):
        raise ResourceNotFound("backup artifact expired or deleted")

    return backup_file, f"quirebase_backup_{job.id[:8]}.zip"
