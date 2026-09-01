import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from filelock import FileLock
from sqlalchemy import select, text

from quirebase.core.config import Settings
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.revisions import (
    create_attachment,
    delete_unreferenced_objects,
    store_pdf_revision,
)
from quirebase.models import Attachment, AttachmentRole, Item, User


def test_content_addressed_pdf_storage_is_idempotent(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    content = b"%PDF-1.4\nminimal"
    first = store.put_pdf(BytesIO(content), 100)
    second = store.put_pdf(BytesIO(content), 100)

    assert first == second
    assert store.path(first[0]).read_bytes() == content


def test_storage_rejects_non_pdf_and_oversize(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError, match="not a PDF"):
        store.put_pdf(BytesIO(b"hello"), 100)
    with pytest.raises(ValueError, match="size limit"):
        store.put_pdf(BytesIO(b"%PDF-" + b"x" * 20), 10)


def test_staged_object_cleanup_does_not_leave_per_object_directories(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    key, _digest, _size, lease = store.put_staged_pdf(
        BytesIO(b"%PDF-1.4\nminimal"),
        100,
    )

    lease.release()
    store.delete(key)

    assert not store.path(key).parent.exists()
    assert not list(store.settings.object_dir.rglob("leases"))
    assert len([path for path in store.settings.object_dir.rglob("*") if path.is_dir()]) <= 1


def test_cleanup_lock_can_be_released_from_another_worker_thread(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    lock = store.cleanup_lock("aa/bb/object.pdf")
    acquired = False
    with (
        ThreadPoolExecutor(max_workers=1) as acquiring_worker,
        ThreadPoolExecutor(max_workers=1) as releasing_worker,
    ):
        acquiring_worker.submit(lock.acquire).result()
        try:
            releasing_worker.submit(lock.release).result()
            probe = FileLock(lock.lock_file)
            probe.acquire(blocking=False)
            acquired = True
            probe.release()
        finally:
            if not acquired:
                acquiring_worker.submit(lock.release, True).result()


def test_object_lease_can_be_released_from_another_worker_thread(tmp_path):
    store = LocalObjectStore(Settings(data_dir=tmp_path))
    with (
        ThreadPoolExecutor(max_workers=1) as staging_worker,
        ThreadPoolExecutor(max_workers=1) as releasing_worker,
    ):
        key, _digest, _size, lease = staging_worker.submit(
            store.put_staged_pdf,
            BytesIO(b"%PDF-1.4\nminimal"),
            100,
        ).result()
        releasing_worker.submit(lease.release).result()
        still_locked = staging_worker.submit(lambda: lease._lock.is_locked).result()
        if still_locked:
            staging_worker.submit(lease._lock.release, True).result()

    assert not still_locked
    store.delete(key)


@pytest.mark.anyio
async def test_database_fixture_isolates_the_default_object_store(async_db, tmp_path):
    assert await async_db.scalar(text("SELECT 1")) == 1
    store = LocalObjectStore()

    assert store.settings.data_dir == tmp_path / "async-data"


@pytest.mark.anyio
async def test_attachment_upload_lease_prevents_concurrent_cleanup(
    async_db, async_session_factory, monkeypatch
):
    db = async_db
    user = User(username="attachment-uploader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Attachment lease", created_by=user.id)
    db.add(item)
    await db.commit()
    original_commit = db.commit
    store = LocalObjectStore()

    async def commit_while_cleanup_runs():
        object_path = next(store.settings.object_dir.glob("*/*/*.bin"))
        object_key = str(object_path.relative_to(store.settings.object_dir))
        async with async_session_factory() as concurrent_db:
            deleted = await delete_unreferenced_objects(concurrent_db, (object_key,))
        assert deleted == ()
        assert object_path.exists()
        await original_commit()

    monkeypatch.setattr(db, "commit", commit_while_cleanup_runs)

    attachment = await create_attachment(
        db,
        user,
        item.id,
        BytesIO(b"same bytes as a concurrently deleted attachment"),
        "supplement.txt",
        "text/plain",
    )

    assert store.path(attachment.object_key).exists()


@pytest.mark.anyio
async def test_cancelled_pdf_staging_reclaims_completed_thread_result(async_db, monkeypatch):
    from quirebase.documents import revisions

    db = async_db
    user = User(username="cancelled-pdf-uploader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Cancelled PDF", created_by=user.id)
    db.add(item)
    await db.commit()
    started = asyncio.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    loop = asyncio.get_running_loop()
    original_stage_pdf = revisions.stage_pdf
    monkeypatch.setattr(revisions, "validate_pdf_container", lambda _path: None)

    def delayed_stage_pdf(source, filename, maximum):
        loop.call_soon_threadsafe(started.set)
        release_worker.wait()
        try:
            return original_stage_pdf(source, filename, maximum)
        finally:
            worker_finished.set()

    monkeypatch.setattr(revisions, "stage_pdf", delayed_stage_pdf)
    upload = asyncio.create_task(
        store_pdf_revision(
            db,
            user,
            item.id,
            BytesIO(b"%PDF-1.4\ncancelled"),
            "cancelled.pdf",
            100,
        )
    )
    await started.wait()
    upload.cancel()
    release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await upload
    assert await asyncio.to_thread(worker_finished.wait, 1)
    assert list(LocalObjectStore().settings.object_dir.rglob("*.pdf")) == []


@pytest.mark.anyio
async def test_cancelled_attachment_staging_reclaims_completed_thread_result(async_db, monkeypatch):
    db = async_db
    user = User(username="cancelled-attachment-uploader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Cancelled attachment", created_by=user.id)
    db.add(item)
    await db.commit()
    started = asyncio.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    loop = asyncio.get_running_loop()
    original_put = LocalObjectStore.put_staged_attachment

    def delayed_put(store, source, maximum):
        loop.call_soon_threadsafe(started.set)
        release_worker.wait()
        try:
            return original_put(store, source, maximum)
        finally:
            worker_finished.set()

    monkeypatch.setattr(LocalObjectStore, "put_staged_attachment", delayed_put)
    upload = asyncio.create_task(
        create_attachment(
            db,
            user,
            item.id,
            BytesIO(b"cancelled attachment"),
            "cancelled.txt",
            "text/plain",
            100,
        )
    )
    await started.wait()
    upload.cancel()
    release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await upload
    assert await asyncio.to_thread(worker_finished.wait, 1)
    assert list(LocalObjectStore().settings.object_dir.rglob("*.bin")) == []


@pytest.mark.anyio
async def test_concurrent_graphical_abstract_uploads_are_serialized(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="concurrent-attachment-uploader", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Concurrent graphical abstract", created_by=user.id)
    db.add(item)
    await db.commit()
    user_id, item_id = user.id, item.id

    start = asyncio.Barrier(2)

    async def upload(index: int) -> str:
        async with async_session_factory() as worker_db:
            worker_user = await worker_db.get(User, user_id)
            assert worker_user is not None
            await start.wait()
            attachment = await create_attachment(
                worker_db,
                worker_user,
                item_id,
                BytesIO(b"\x89PNG\r\n\x1a\n" + bytes([index])),
                f"abstract-{index}.png",
                "image/png",
                role=AttachmentRole.graphical_abstract,
            )
            return attachment.id

    attachment_ids = await asyncio.gather(upload(0), upload(1))

    attachments = (
        await db.scalars(select(Attachment).where(Attachment.id.in_(attachment_ids)))
    ).all()
    assert len(attachments) == 2
    assert sum(record.role == AttachmentRole.graphical_abstract for record in attachments) == 1
