from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID, uuid5

from sqlalchemy import select

from quirebase.core.storage import (
    ObjectStore,
    ObjectSuffix,
    get_object_store,
    is_legacy_cas_key,
    is_managed_object_key,
    object_key,
)
from quirebase.models import Attachment, FileRevision, ImportBatch

OBJECT_MIGRATION_NAMESPACE = UUID("9a8c5b31-a356-5c30-884d-45c17722d8b8")


@dataclass(frozen=True)
class ObjectMigrationReport:
    planned: int
    copied: int
    references_updated: int
    legacy_deleted: int


def _stable_uuid(kind: str, identity: str) -> UUID:
    try:
        return UUID(identity)
    except ValueError:
        return uuid5(OBJECT_MIGRATION_NAMESPACE, f"{kind}:{identity}")


async def _copy_verified(
    store: ObjectStore,
    old_key: str,
    target_id: UUID,
    suffix: ObjectSuffix,
    expected_size: int,
) -> tuple[str, bool]:
    target_key = object_key(target_id, suffix)
    if await store.exists(target_key):
        if (await store.head(target_key)).size != expected_size:
            raise ValueError(f"migration target size mismatch: {target_key}")
        return target_key, False
    if not await store.exists(old_key):
        raise FileNotFoundError(old_key)
    metadata = await store.head(old_key)
    if metadata.size != expected_size:
        raise ValueError(f"legacy object size mismatch: {old_key}")
    response = await store.get(old_key)
    copied = await store.put_object(
        target_id,
        suffix,
        response.body,
        max_bytes=metadata.size,
    )
    if copied.size != expected_size:
        raise ValueError(f"copied object size mismatch: {target_key}")
    return target_key, True


def _pdf_rows(records_json: str) -> list[dict]:
    try:
        records = json.loads(records_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return records if isinstance(records, list) else []


async def migrate_legacy_objects(db, *, apply: bool = False) -> ObjectMigrationReport:
    """Plan or perform the repeatable, stopped-instance CAS-to-UUID migration."""
    store = get_object_store()
    revisions = list((await db.scalars(select(FileRevision).order_by(FileRevision.id))).all())
    attachments = list((await db.scalars(select(Attachment).order_by(Attachment.id))).all())
    batches = list((await db.scalars(select(ImportBatch).order_by(ImportBatch.id))).all())
    planned = copied = updated = deleted = 0
    obsolete_keys: set[str] = set()

    for revision in revisions:
        if not is_managed_object_key(revision.object_key):
            if not is_legacy_cas_key(revision.object_key):
                raise ValueError(f"unsupported File Revision object key: {revision.object_key}")
            planned += 1
            obsolete_keys.add(revision.object_key)
            if apply:
                target, did_copy = await _copy_verified(
                    store,
                    revision.object_key,
                    _stable_uuid("revision", revision.id),
                    ObjectSuffix.PDF,
                    revision.size,
                )
                copied += int(did_copy)
                revision.object_key = target
                updated += 1
                await db.commit()
        legacy_thumbnail = f"thumbnails/{revision.id}.png"
        if await store.exists(legacy_thumbnail):
            planned += 1
            obsolete_keys.add(legacy_thumbnail)
            if apply:
                expected = (await store.head(legacy_thumbnail)).size
                target, did_copy = await _copy_verified(
                    store,
                    legacy_thumbnail,
                    uuid5(OBJECT_MIGRATION_NAMESPACE, f"thumbnail:{revision.id}"),
                    ObjectSuffix.PNG,
                    expected,
                )
                copied += int(did_copy)
                if revision.thumbnail_object_key != target:
                    revision.thumbnail_object_key = target
                    updated += 1
                    await db.commit()

    for attachment in attachments:
        if is_managed_object_key(attachment.object_key):
            continue
        if not is_legacy_cas_key(attachment.object_key):
            raise ValueError(f"unsupported Attachment object key: {attachment.object_key}")
        planned += 1
        obsolete_keys.add(attachment.object_key)
        if apply:
            target, did_copy = await _copy_verified(
                store,
                attachment.object_key,
                _stable_uuid("attachment", attachment.id),
                ObjectSuffix.BINARY,
                attachment.size,
            )
            copied += int(did_copy)
            attachment.object_key = target
            updated += 1
            await db.commit()

    for batch in batches:
        records = _pdf_rows(batch.records)
        changed = False
        for index, row in enumerate(records):
            pdf = row.get("_pdf") if isinstance(row, dict) else None
            if not isinstance(pdf, dict) or not isinstance(pdf.get("object_key"), str):
                continue
            old_key = pdf["object_key"]
            if is_managed_object_key(old_key):
                continue
            if not is_legacy_cas_key(old_key):
                raise ValueError(f"unsupported Import Batch object key: {old_key}")
            import_size = pdf.get("size")
            if not isinstance(import_size, int) or import_size < 0:
                raise ValueError(f"Import Batch object has no valid size: {old_key}")
            planned += 1
            obsolete_keys.add(old_key)
            if apply:
                target, did_copy = await _copy_verified(
                    store,
                    old_key,
                    uuid5(
                        OBJECT_MIGRATION_NAMESPACE,
                        f"import:{batch.id}:{index}:{old_key}",
                    ),
                    ObjectSuffix.PDF,
                    import_size,
                )
                copied += int(did_copy)
                pdf["object_key"] = target
                changed = True
                updated += 1
        if apply and changed:
            batch.records = json.dumps(records, ensure_ascii=False)
            await db.commit()

    if apply:
        referenced = {
            *(await db.scalars(select(FileRevision.object_key))).all(),
            *(await db.scalars(select(Attachment.object_key))).all(),
        }
        for batch in (await db.scalars(select(ImportBatch.records))).all():
            for row in _pdf_rows(batch):
                if isinstance(row, dict) and isinstance(row.get("_pdf"), dict):
                    key = row["_pdf"].get("object_key")
                    if isinstance(key, str):
                        referenced.add(key)
        for key in sorted(obsolete_keys - referenced):
            deleted += int(await store.delete(key))
        async for artifact in store.iter_prefix("artifacts/annotation-exports/"):
            deleted += int(await store.delete(artifact.key))

    return ObjectMigrationReport(planned, copied, updated, deleted)
