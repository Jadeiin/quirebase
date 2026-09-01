"""Streaming Document bundles and single-revision exports."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from stat import S_IFREG
from typing import TYPE_CHECKING, Any

import stream_zip
from inquiro.richtext import convert_rich_text
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from quirebase.access.documents import require_revision
from quirebase.access.items import require_accessible_items
from quirebase.audit import record_event
from quirebase.core.errors import ResourceNotFound
from quirebase.core.storage import get_object_store
from quirebase.core.timezones import annotation_export_timezone
from quirebase.documents.annotations import select_visible_annotations
from quirebase.models import Attachment, FileRevision, Item, PdfAnnotation, User
from quirebase.pipeline.inspection import export_annotations

if TYPE_CHECKING:
    from collections.abc import AsyncIterable, AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession
    from stream_zip import AsyncMemberFile


@dataclass(frozen=True)
class ItemDownloadBundle:
    body: AsyncIterable[bytes]
    filename: str


@dataclass(frozen=True)
class ExportedRevision:
    body: AsyncIterable[bytes]
    filename: str
    media_type: str = "application/pdf"


def _archive_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^\w.-]+", "-", value, flags=re.UNICODE).strip("-.")
    return (name or fallback)[:80]


def _item_archive_prefix(item: Item) -> str:
    return _archive_name(
        item.bibtex_id or convert_rich_text(item.title, source="html", target="text"),
        item.id[:8],
    )


def _revision_archive_name(
    prefix: str, index: int, original_name: str, *, annotated: bool = False
) -> str:
    safe_name = _archive_name(Path(original_name).name, f"revision-{index:02d}.pdf")
    marker = "annotated-pdf" if annotated else "pdf"
    return f"{prefix}-{marker}-v{index:02d}-{safe_name}"


def _download_kind(include_annotations: bool, include_supplements: bool) -> str:
    if include_annotations and include_supplements:
        return "annotated-bundle"
    if include_annotations:
        return "annotated-pdfs"
    if include_supplements:
        return "bundle"
    return "pdfs"


def _bundle_path(root: str, filename: str) -> str:
    return f"{root}/{filename}" if root else filename


def _temporary_path(*, prefix: str, suffix: str) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(descriptor)
    return Path(name)


class _ActiveReads:
    """Cancel member reads that stream-zip's worker thread still awaits."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Future[Any]] = set()
        self._iterators: set[AsyncIterator[bytes]] = set()

    def add(self, task: asyncio.Future[Any]) -> None:
        self._tasks.add(task)

    def discard(self, task: asyncio.Future[Any]) -> None:
        self._tasks.discard(task)

    def register(self, iterator: AsyncIterator[bytes]) -> None:
        self._iterators.add(iterator)

    def unregister(self, iterator: AsyncIterator[bytes]) -> None:
        self._iterators.discard(iterator)

    async def cancel(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for iterator in tuple(self._iterators):
            close = getattr(iterator, "aclose", None)
            if close is not None:
                with suppress(RuntimeError):
                    await close()


async def _bridge(body: AsyncIterable[bytes], active_reads: _ActiveReads) -> AsyncIterator[bytes]:
    """Preserve cancellation while adapting obstore streams for stream-zip."""
    iterator = body.__aiter__()
    active_reads.register(iterator)
    try:
        while True:
            read = asyncio.ensure_future(iterator.__anext__())
            active_reads.add(read)
            try:
                chunk = await read
            except StopAsyncIteration:
                return
            finally:
                active_reads.discard(read)
            yield bytes(chunk)
    finally:
        active_reads.unregister(iterator)
        close = getattr(iterator, "aclose", None)
        if close is not None:
            await close()


async def _path_body(path: Path, *, delete_after: bool = False) -> AsyncIterator[bytes]:
    source = await asyncio.to_thread(path.open, "rb")
    try:
        while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
            yield chunk
    finally:
        await asyncio.shield(asyncio.to_thread(source.close))
        if delete_after:
            await asyncio.shield(asyncio.to_thread(path.unlink, missing_ok=True))


async def _bytes_body(value: bytes) -> AsyncIterator[bytes]:
    await asyncio.sleep(0)
    yield value


async def _own_annotations(db: AsyncSession, user: User, revision_id: str) -> list[PdfAnnotation]:
    return list(
        (
            await db.scalars(
                select(PdfAnnotation)
                .options(selectinload(PdfAnnotation.segments))
                .where(
                    PdfAnnotation.file_revision_id == revision_id,
                    PdfAnnotation.author_id == user.id,
                    PdfAnnotation.deleted_at.is_(None),
                )
                .order_by(PdfAnnotation.created_at)
            )
        ).all()
    )


async def _revision_member(
    db: AsyncSession,
    user: User,
    revision: FileRevision,
    filename: str,
    *,
    include_annotations: bool,
    timezone: str | None,
    active_reads: _ActiveReads,
) -> AsyncMemberFile:
    store = get_object_store()
    if include_annotations:
        annotations = await _own_annotations(db, user, revision.id)
    else:
        annotations = []
    if annotations:
        target = _temporary_path(prefix="quirebase-annotated-", suffix=".pdf")
        try:
            async with store.materialize(revision.object_key) as source:
                await asyncio.to_thread(
                    export_annotations,
                    source,
                    target,
                    annotations,
                    author_names={user.id: user.username},
                    display_timezone=annotation_export_timezone(timezone),
                )
            size = (await asyncio.to_thread(target.stat)).st_size
        except BaseException:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        body = _bridge(_path_body(target, delete_after=True), active_reads)
    else:
        response = await store.get(revision.object_key)
        size = response.metadata.size
        body = _bridge(response.body, active_reads)
    return (
        filename,
        revision.created_at,
        S_IFREG | 0o644,
        stream_zip.ZIP_AUTO(size),
        body,
    )


async def _item_members(
    db: AsyncSession,
    user: User,
    item: Item,
    *,
    root: str = "",
    revision_ids: list[str] | None = None,
    include_annotations: bool,
    include_supplements: bool,
    timezone: str | None,
    active_reads: _ActiveReads,
) -> AsyncIterator[AsyncMemberFile]:
    query = (
        select(FileRevision)
        .where(FileRevision.item_id == item.id)
        .order_by(FileRevision.created_at.desc())
    )
    if revision_ids:
        query = query.where(FileRevision.id.in_(revision_ids))
    revisions = (await db.scalars(query)).all()
    prefix = _item_archive_prefix(item)
    manifest: list[dict[str, object]] = []
    for index, revision in enumerate(revisions, start=1):
        filename = _revision_archive_name(
            prefix, index, revision.original_name, annotated=include_annotations
        )
        archive_filename = _bundle_path(root, filename)
        yield await _revision_member(
            db,
            user,
            revision,
            archive_filename,
            include_annotations=include_annotations,
            timezone=timezone,
            active_reads=active_reads,
        )
        manifest.append({
            "version": index,
            "revision_id": revision.id,
            "original_name": revision.original_name,
            "filename": archive_filename,
            "created_at": revision.created_at.isoformat(),
            "processing_state": getattr(
                revision.processing_state, "value", revision.processing_state
            ),
        })
    manifest_bytes = json.dumps({"pdf_revisions": manifest}, ensure_ascii=False, indent=2).encode()
    yield (
        _bundle_path(root, "manifest.json"),
        item.updated_at,
        S_IFREG | 0o644,
        stream_zip.ZIP_AUTO(len(manifest_bytes)),
        _bytes_body(manifest_bytes),
    )
    if include_supplements:
        store = get_object_store()
        attachments = (
            await db.scalars(
                select(Attachment)
                .where(Attachment.item_id == item.id)
                .order_by(Attachment.created_at)
            )
        ).all()
        for index, attachment in enumerate(attachments, start=1):
            safe_name = _archive_name(
                Path(attachment.original_name).name, f"supplement-{index:02d}"
            )
            response = await store.get(attachment.object_key)
            yield (
                _bundle_path(root, f"supplements/{index:02d}-{safe_name}"),
                attachment.created_at,
                S_IFREG | 0o644,
                stream_zip.ZIP_AUTO(response.metadata.size),
                _bridge(response.body, active_reads),
            )


async def _zip_body(
    members: AsyncIterable[AsyncMemberFile], active_reads: _ActiveReads
) -> AsyncIterator[bytes]:
    archive = stream_zip.async_stream_zip(members)
    try:
        async for chunk in archive:
            yield chunk
    finally:
        await active_reads.cancel()
        close = getattr(archive, "aclose", None)
        if close is not None:
            await close()


async def create_item_document_bundle(
    db: AsyncSession,
    user: User,
    item_id: str,
    *,
    revision_ids: list[str] | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    item = (await require_accessible_items(db, user, [item_id]))[0]
    prefix = _item_archive_prefix(item)
    record_event(
        db,
        user.id,
        "item.download_bundle",
        "item",
        item.id,
        detail={
            "include_annotations": include_annotations,
            "include_supplements": include_supplements,
            "revision_ids": revision_ids or [],
        },
    )
    await db.commit()
    active_reads = _ActiveReads()
    members = _item_members(
        db,
        user,
        item,
        revision_ids=revision_ids,
        include_annotations=include_annotations,
        include_supplements=include_supplements,
        timezone=timezone,
        active_reads=active_reads,
    )
    kind = _download_kind(include_annotations, include_supplements)
    return ItemDownloadBundle(
        body=_zip_body(members, active_reads),
        filename=f"{prefix}-{kind}.zip",
    )


async def assemble_document_bundle(
    db: AsyncSession,
    user: User,
    items: list[Item],
    *,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
) -> ItemDownloadBundle:
    await asyncio.sleep(0)
    active_reads = _ActiveReads()

    async def members() -> AsyncIterator[AsyncMemberFile]:
        item_manifest = []
        used_roots: set[str] = set()
        for item in items:
            root = _item_archive_prefix(item)
            if root in used_roots:
                root = f"{root}-{item.id[:8]}"
            used_roots.add(root)
            async for member in _item_members(
                db,
                user,
                item,
                root=root,
                include_annotations=include_annotations,
                include_supplements=include_supplements,
                timezone=timezone,
                active_reads=active_reads,
            ):
                yield member
            item_manifest.append({
                "item_id": item.id,
                "title": convert_rich_text(item.title, source="html", target="text"),
                "folder": root,
            })
        value = json.dumps({"items": item_manifest}, ensure_ascii=False, indent=2).encode()
        yield (
            "manifest.json",
            items[0].updated_at,
            S_IFREG | 0o644,
            stream_zip.ZIP_AUTO(len(value)),
            _bytes_body(value),
        )

    kind = _download_kind(include_annotations, include_supplements)
    member_stream = members()
    return ItemDownloadBundle(
        body=_zip_body(member_stream, active_reads),
        filename=f"quirebase-selected-{kind}.zip",
    )


async def _record_revision_pdf_export(
    db: AsyncSession,
    user: User,
    item_id: str,
    revision_id: str,
    *,
    include_annotations: bool,
    project_id: str | None,
) -> None:
    record_event(
        db,
        user.id,
        "item.download_revision_pdf",
        "revision",
        revision_id,
        detail={
            "item_id": item_id,
            "include_annotations": include_annotations,
            "project_id": project_id,
        },
    )
    await db.commit()


async def export_revision_pdf(
    db: AsyncSession,
    user: User,
    item_id: str,
    revision_id: str,
    *,
    include_annotations: bool = True,
    project_id: str | None = None,
    timezone: str | None = None,
) -> ExportedRevision:
    revision = await require_revision(db, user, revision_id)
    if revision.item_id != item_id:
        raise ResourceNotFound("revision not found for item")
    annotations = (
        await select_visible_annotations(db, user, revision.id, item_id, project_id)
        if include_annotations
        else []
    )
    store = get_object_store()
    if annotations:
        target = _temporary_path(prefix="quirebase-export-", suffix=".pdf")
        try:
            author_names = {user.id: user.username}
            if project_id:
                rows = (
                    await db.execute(
                        select(User.id, User.username).where(
                            User.id.in_({record.author_id for record in annotations})
                        )
                    )
                ).all()
                author_names = {row[0]: row[1] for row in rows}
            async with store.materialize(revision.object_key) as source:
                await asyncio.to_thread(
                    export_annotations,
                    source,
                    target,
                    annotations,
                    author_names=author_names,
                    display_timezone=annotation_export_timezone(timezone),
                )
            safe_name = _archive_name(Path(revision.original_name).stem, "document")
            filename = f"{safe_name}-annotated.pdf"
        except BaseException:
            await asyncio.to_thread(target.unlink, missing_ok=True)
            raise
        body: AsyncIterable[bytes] = _path_body(target, delete_after=True)
    else:
        response = await store.get(revision.object_key)
        body = response.body
        filename = revision.original_name
    try:
        await _record_revision_pdf_export(
            db,
            user,
            item_id,
            revision_id,
            include_annotations=include_annotations,
            project_id=project_id,
        )
    except BaseException:
        if annotations:
            await asyncio.to_thread(target.unlink, missing_ok=True)
        raise
    return ExportedRevision(body=body, filename=filename)
