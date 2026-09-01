import asyncio
import hashlib
import os
import tempfile
import threading

import pymupdf
import pytest
from obstore.store import LocalStore

from quirebase.core.config import Settings
from quirebase.core.storage import ObjectStore
from quirebase.documents.revisions import stage_pdf
from quirebase.models import FileRevision, Item, User


async def chunks(value: bytes, size: int = 7):
    for offset in range(0, len(value), size):
        await asyncio.sleep(0)
        yield value[offset : offset + size]


def test_s3_store_omits_unset_optional_configuration(monkeypatch, tmp_path):
    constructed = {}

    class StubS3Store:
        def __init__(self, bucket, **options):
            constructed["bucket"] = bucket
            constructed["options"] = options

    monkeypatch.setattr("quirebase.core.storage.S3Store", StubS3Store)

    ObjectStore.from_settings(Settings(data_dir=tmp_path, object_store="s3", s3_bucket="documents"))

    assert constructed == {
        "bucket": "documents",
        "options": {"client_options": {"timeout": "5m"}},
    }


@pytest.mark.anyio
async def test_local_cleanup_lock_serializes_delete_and_cas_publish(tmp_path):
    store = ObjectStore.from_settings(Settings(data_dir=tmp_path))
    content = b"immutable content"
    digest = hashlib.sha256(content).hexdigest()
    key = f"{digest[:2]}/{digest[2:4]}/{digest}.bin"
    delete_started = asyncio.Event()
    allow_delete = asyncio.Event()
    data_plane = store._store

    class BlockingDeleteStore:
        def __getattr__(self, name):
            return getattr(data_plane, name)

        async def delete_async(self, object_key):
            delete_started.set()
            await allow_delete.wait()
            await data_plane.delete_async(object_key)

    store._store = BlockingDeleteStore()
    deleting = asyncio.create_task(store.delete(key))
    await delete_started.wait()
    uploading = asyncio.create_task(store.put_cas(content, suffix=".bin", max_bytes=len(content)))
    try:
        await asyncio.sleep(0.05)
        upload_waited_for_delete = not uploading.done()
    finally:
        allow_delete.set()
    await deleting
    staged = await uploading

    assert upload_waited_for_delete
    assert await store.exists(key)
    await staged.release()
    await store.delete(key)


@pytest.mark.anyio
@pytest.mark.parametrize("remote_materialization", [False, True])
async def test_cancelled_pdf_validation_waits_for_validator_then_reclaims_object(
    async_db, tmp_path, monkeypatch, remote_materialization
):
    root = tmp_path / "data-plane"
    data_plane = LocalStore(root, mkdir=True, automatic_cleanup=True)
    store = ObjectStore(data_plane, local_root=None if remote_materialization else root)
    started = threading.Event()
    finish = threading.Event()
    materialized_paths = []

    def blocking_validation(path):
        materialized_paths.append(path)
        started.set()
        assert finish.wait(timeout=5)
        assert path.is_file()

    monkeypatch.setattr("quirebase.documents.revisions.get_object_store", lambda: store)
    monkeypatch.setattr("quirebase.documents.revisions.validate_pdf_container", blocking_validation)
    content = b"%PDF-cancelled-validation"
    digest = hashlib.sha256(content).hexdigest()
    key = f"{digest[:2]}/{digest[2:4]}/{digest}.pdf"
    staging = asyncio.create_task(stage_pdf(async_db, content, "cancelled.pdf", len(content)))
    await asyncio.to_thread(started.wait, 5)
    staging.cancel()
    try:
        await asyncio.sleep(0.05)
        assert not staging.done()
        assert materialized_paths[0].is_file()
    finally:
        finish.set()

    with pytest.raises(asyncio.CancelledError):
        await staging
    assert not await store.exists(key)
    assert not materialized_paths[0].exists()
    assert not list(root.rglob("*.lease.lock"))


@pytest.mark.anyio
async def test_cancelled_duplicate_pdf_validation_preserves_referenced_cas_object(
    async_db, tmp_path, monkeypatch
):
    db = async_db
    root = tmp_path / "objects"
    store = ObjectStore(LocalStore(root, mkdir=True), local_root=root)
    content = b"%PDF-referenced-duplicate"
    digest = hashlib.sha256(content).hexdigest()
    key = f"{digest[:2]}/{digest[2:4]}/{digest}.pdf"
    await store.put(key, content)
    user = User(username="cas-owner", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="Referenced CAS", created_by=user.id)
    db.add(item)
    await db.flush()
    db.add(
        FileRevision(
            item_id=item.id,
            object_key=key,
            sha256=digest,
            size=len(content),
            original_name="existing.pdf",
            processing_state="ready",
            created_by=user.id,
        )
    )
    await db.commit()
    started = threading.Event()
    finish = threading.Event()

    def blocking_validation(path):
        started.set()
        assert finish.wait(timeout=5)

    monkeypatch.setattr("quirebase.documents.revisions.get_object_store", lambda: store)
    monkeypatch.setattr("quirebase.documents.revisions.validate_pdf_container", blocking_validation)
    staging = asyncio.create_task(stage_pdf(db, content, "duplicate.pdf", len(content)))
    await asyncio.to_thread(started.wait, 5)
    staging.cancel()
    finish.set()

    with pytest.raises(asyncio.CancelledError):
        await staging
    assert await store.exists(key)
    assert not list(root.rglob("*.lease.lock"))


@pytest.mark.anyio
async def test_cas_publish_does_not_depend_on_post_upload_head(tmp_path):
    data_plane = LocalStore(tmp_path / "data-plane", mkdir=True)

    class HeadFailingStore:
        def __getattr__(self, name):
            return getattr(data_plane, name)

        async def head_async(self, key):
            raise RuntimeError("injected post-upload HEAD failure")

    store = ObjectStore(HeadFailingStore())
    content = b"cas without post-upload head"
    staged = await store.put_cas(content, suffix=".bin", max_bytes=len(content))

    metadata = await data_plane.head_async(staged.key)
    assert metadata["size"] == len(content)


@pytest.fixture(params=["local", "s3"])
def object_store(request, tmp_path):
    if request.param == "local":
        return ObjectStore.from_settings(Settings(data_dir=tmp_path))
    endpoint = os.getenv("QUIREBASE_TEST_S3_ENDPOINT")
    bucket = os.getenv("QUIREBASE_TEST_S3_BUCKET")
    if not endpoint or not bucket:
        pytest.skip("S3 contract requires QUIREBASE_TEST_S3_ENDPOINT and bucket")
    prefix = f"contract/{tmp_path.name}"
    return ObjectStore.from_settings(
        Settings(
            data_dir=tmp_path,
            object_store="s3",
            s3_bucket=bucket,
            s3_endpoint=endpoint,
            s3_region=os.getenv("QUIREBASE_TEST_S3_REGION", "us-east-1"),
            s3_prefix=prefix,
        )
    )


@pytest.mark.anyio
async def test_object_store_upload_head_range_and_delete(object_store):
    content = b"0123456789" * 20
    metadata = await object_store.put("contract/data.bin", chunks(content))

    assert metadata.size == len(content)
    assert await object_store.exists("contract/data.bin")
    response = await object_store.get_range("contract/data.bin", 7, 31)
    assert b"".join([bytes(part) async for part in response.body]) == content[7:31]
    assert response.byte_range == (7, 31)
    assert await object_store.delete("contract/data.bin")
    assert not await object_store.exists("contract/data.bin")


@pytest.mark.anyio
async def test_object_store_put_accepts_path_bytes_and_async_iterable(object_store, tmp_path):
    path = tmp_path / "source.bin"
    path.write_bytes(b"path")

    await object_store.put("contract/path.bin", path)
    await object_store.put("contract/bytes.bin", b"bytes")
    await object_store.put("contract/stream.bin", chunks(b"stream"))

    for key, expected in (
        ("contract/path.bin", b"path"),
        ("contract/bytes.bin", b"bytes"),
        ("contract/stream.bin", b"stream"),
    ):
        response = await object_store.get(key)
        assert b"".join([bytes(part) async for part in response.body]) == expected


@pytest.mark.anyio
async def test_concurrent_cas_uses_immutable_atomic_overwrite(object_store):
    content = b"same immutable content" * 100_000
    first, second = await asyncio.gather(
        object_store.put_cas(chunks(content), suffix=".bin", max_bytes=len(content)),
        object_store.put_cas(chunks(content), suffix=".bin", max_bytes=len(content)),
    )
    await first.release()
    await second.release()

    assert first.key == second.key
    response = await object_store.get(first.key)
    assert b"".join([bytes(part) async for part in response.body]) == content


@pytest.mark.anyio
async def test_materialize_opens_with_pymupdf(object_store):
    document = pymupdf.open()
    document.new_page()
    pdf = document.tobytes()
    document.close()
    staged = await object_store.put_cas(
        pdf, suffix=".pdf", max_bytes=len(pdf), required_prefix=b"%PDF-"
    )
    await staged.release()

    async with object_store.materialize(staged.key) as path:
        with pymupdf.open(path) as materialized:
            assert materialized.page_count == 1


@pytest.mark.anyio
async def test_cancelled_cas_cleans_temporary_input(object_store, tmp_path, monkeypatch):
    started = asyncio.Event()

    async def blocked():
        started.set()
        yield b"partial"
        await asyncio.Event().wait()

    real_mkstemp = tempfile.mkstemp

    def task_mkstemp(*, prefix, suffix=""):
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr("quirebase.core.storage.tempfile.mkstemp", task_mkstemp)
    task = asyncio.create_task(object_store.put_cas(blocked(), suffix=".bin", max_bytes=100))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("quirebase-cas-*"))


@pytest.mark.anyio
async def test_cancelled_streaming_put_does_not_publish_partial_object(object_store):
    first_part_consumed = asyncio.Event()

    async def multipart_source():
        yield b"x" * (6 * 1024 * 1024)
        first_part_consumed.set()
        await asyncio.Event().wait()

    key = "contract/cancelled-multipart.bin"
    task = asyncio.create_task(object_store.put(key, multipart_source()))
    await asyncio.wait_for(first_part_consumed.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not await object_store.exists(key)


@pytest.mark.anyio
async def test_materialize_scope_cleans_remote_temporary_file_on_cancellation(
    object_store, tmp_path, monkeypatch
):
    await object_store.put("contract/materialize-cancel.bin", b"materialized")
    real_mkstemp = tempfile.mkstemp

    def task_mkstemp(*, prefix, suffix=""):
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr("quirebase.core.storage.tempfile.mkstemp", task_mkstemp)
    entered = asyncio.Event()

    async def hold_materialized_path():
        async with object_store.materialize("contract/materialize-cancel.bin"):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(hold_materialized_path())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not list(tmp_path.glob("quirebase-object-*"))
