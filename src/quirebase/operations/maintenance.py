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

from sqlalchemy import delete, select

from quirebase.core.config import get_settings
from quirebase.core.database import is_sqlite_database_url
from quirebase.core.storage import get_object_store, is_managed_object_key
from quirebase.core.workflows import (
    durable_operations,
    list_active_workflows,
)
from quirebase.models import Attachment, ExportArtifact, FileRevision, ImportBatch, User

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
    await db.rollback()
    if not artifacts:
        return removed
    result = await delete_export_artifact_objects(artifacts)
    removed += result["removed"]
    await delete_export_artifact_records(db, result["workflow_ids"])
    await db.commit()
    return removed


async def cleanup_local_exports(ttl_hours: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
    return await asyncio.to_thread(_cleanup_exports, get_settings().export_dir, cutoff)


async def list_expired_export_artifacts(db: AsyncSession, limit: int) -> tuple[dict[str, str], ...]:
    rows = (
        await db.execute(
            select(ExportArtifact.workflow_id, ExportArtifact.object_key)
            .where(ExportArtifact.expires_at <= datetime.now(UTC))
            .order_by(ExportArtifact.expires_at, ExportArtifact.workflow_id)
            .limit(limit)
        )
    ).all()
    return tuple(
        {"workflow_id": workflow_id, "object_key": object_key} for workflow_id, object_key in rows
    )


async def delete_export_artifact_objects(
    artifacts: tuple[dict[str, str], ...],
) -> dict[str, Any]:
    store = get_object_store()
    removed = 0
    for artifact in artifacts:
        if await store.delete(artifact["object_key"]):
            removed += 1
    return {
        "workflow_ids": [artifact["workflow_id"] for artifact in artifacts],
        "removed": removed,
    }


async def delete_export_artifact_records(db: AsyncSession, workflow_ids: list[str]) -> int:
    if not workflow_ids:
        return 0
    await db.execute(delete(ExportArtifact).where(ExportArtifact.workflow_id.in_(workflow_ids)))
    return len(workflow_ids)


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
) -> tuple[list[str], tuple[str, ...], dict[str, int]]:
    """Check references and find old orphans using one Object Store listing."""
    effective_hours = retention_hours or get_settings().object_orphan_retention_hours
    cutoff = datetime.now(UTC) - timedelta(hours=effective_hours)
    revisions = (
        await db.execute(
            select(
                FileRevision.id,
                FileRevision.object_key,
                FileRevision.size,
                FileRevision.thumbnail_object_key,
                FileRevision.thumbnail_size,
            )
        )
    ).all()
    attachments = (
        await db.execute(select(Attachment.id, Attachment.object_key, Attachment.size))
    ).all()
    export_keys = set((await db.scalars(select(ExportArtifact.object_key))).all())
    referenced = (
        {revision.object_key for revision in revisions}
        | {revision.thumbnail_object_key for revision in revisions if revision.thumbnail_object_key}
        | {attachment.object_key for attachment in attachments}
        | export_keys
    )
    for records in (await db.scalars(select(ImportBatch.records))).all():
        referenced.update(_import_object_keys(records))
    await db.rollback()
    active = await list_active_workflows()
    active_keys = set().union(
        *(
            _workflow_owned_object_keys(workflow.attributes)
            for workflow in active
            if workflow.name != "documents.cleanup_objects"
        )
    )
    stored = {item.key: item async for item in get_object_store().iter_prefix("")}
    errors: list[str] = []
    thumbnail_sizes: dict[str, int] = {}
    for revision in revisions:
        item = stored.get(revision.object_key)
        if item is None:
            errors.append(f"{revision.id}: missing object")
        elif item.size != revision.size:
            errors.append(f"{revision.id}: size mismatch")
        if revision.thumbnail_object_key:
            thumbnail = stored.get(revision.thumbnail_object_key)
            if thumbnail is None:
                errors.append(f"{revision.id}: missing thumbnail")
            elif revision.thumbnail_size is None:
                thumbnail_sizes[revision.id] = thumbnail.size
            elif thumbnail.size != revision.thumbnail_size:
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
        and item.key not in referenced
        and item.key not in active_keys
    )
    return errors, candidates, thumbnail_sizes


def _import_object_keys(records_json: str) -> set[str]:
    try:
        rows = json.loads(records_json)
    except (json.JSONDecodeError, TypeError):
        return set()
    if not isinstance(rows, list):
        return set()
    return {
        key
        for row in rows
        if isinstance(row, dict)
        and isinstance((pdf := row.get("_pdf")), dict)
        and isinstance((key := pdf.get("object_key")), str)
    }


async def _referenced_object_keys(db: AsyncSession) -> set[str]:
    keys = set((await db.scalars(select(FileRevision.object_key))).all())
    keys.update(
        key for key in (await db.scalars(select(FileRevision.thumbnail_object_key))).all() if key
    )
    keys.update((await db.scalars(select(Attachment.object_key))).all())
    for records in (await db.scalars(select(ImportBatch.records))).all():
        keys.update(_import_object_keys(records))
    return keys


def _workflow_owned_object_keys(attributes: dict[str, Any] | None) -> set[str]:
    if not attributes:
        return set()
    raw_keys = attributes.get("object_keys")
    keys = (
        {key for key in raw_keys if isinstance(key, str)}
        if isinstance(raw_keys, (list, tuple))
        else set()
    )
    if isinstance((key := attributes.get("object_key")), str):
        keys.add(key)
    return keys


async def reconcile_objects(
    db: AsyncSession, *, retention_hours: int | None = None
) -> tuple[str, ...]:
    """Delete only old, managed UUID objects that remain unreferenced on recheck."""
    _errors, candidates, _thumbnail_sizes = await scan_objects(db, retention_hours=retention_hours)
    return await delete_orphan_candidates(db, candidates)


async def delete_orphan_candidates(
    db: AsyncSession, candidates: tuple[str, ...]
) -> tuple[str, ...]:
    """Recheck all candidate protections once, then delete remaining objects."""
    if not candidates:
        return ()
    referenced = await _referenced_object_keys(db)
    await db.rollback()
    active = await list_active_workflows()
    active_keys = set().union(
        *(
            _workflow_owned_object_keys(workflow.attributes)
            for workflow in active
            if workflow.name != "documents.cleanup_objects"
        )
    )
    deleted: list[str] = []
    store = get_object_store()
    for key in candidates:
        if key in referenced or key in active_keys:
            continue
        if await store.delete(key):
            deleted.append(key)
    return tuple(deleted)


async def get_backup_artifact(db: AsyncSession, admin: User, workflow_id: str) -> tuple[Path, str]:
    from quirebase.core.errors import ResourceNotFound, ResourceUnavailable

    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
    del db
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
