import asyncio
import os
import tempfile
from uuid import UUID, uuid4

import pymupdf
import pytest

from quirebase.core.config import Settings
from quirebase.core.storage import (
    ObjectStore,
    ObjectSuffix,
    is_legacy_cas_key,
    is_managed_object_key,
    object_key,
)


async def chunks(value: bytes, size: int = 7):
    for offset in range(0, len(value), size):
        await asyncio.sleep(0)
        yield value[offset : offset + size]


def test_object_key_is_strict_two_level_uuid_layout():
    object_id = UUID("abcdef01-2345-6789-abcd-ef0123456789")
    assert object_key(object_id, ObjectSuffix.PDF) == ("ab/cd/abcdef0123456789abcdef0123456789.pdf")
    assert is_managed_object_key("ab/cd/abcdef0123456789abcdef0123456789.pdf")
    assert not is_managed_object_key("ac/cd/abcdef0123456789abcdef0123456789.pdf")
    assert not is_managed_object_key("ab/cd/abcdef0123456789abcdef0123456789.exe")
    assert is_legacy_cas_key("aa/bb/" + "0" * 64 + ".pdf")
    assert not is_legacy_cas_key(".doctor/probe")


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


@pytest.fixture(params=["local", "s3"])
def object_store(request, tmp_path):
    if request.param == "local":
        return ObjectStore.from_settings(Settings(data_dir=tmp_path))
    endpoint = os.getenv("QUIREBASE_TEST_S3_ENDPOINT")
    bucket = os.getenv("QUIREBASE_TEST_S3_BUCKET")
    if not endpoint or not bucket:
        pytest.skip("S3 contract requires QUIREBASE_TEST_S3_ENDPOINT and bucket")
    return ObjectStore.from_settings(
        Settings(
            data_dir=tmp_path,
            object_store="s3",
            s3_bucket=bucket,
            s3_endpoint=endpoint,
            s3_region=os.getenv("QUIREBASE_TEST_S3_REGION", "us-east-1"),
            s3_prefix=f"contract/{tmp_path.name}",
        )
    )


@pytest.mark.anyio
async def test_object_store_upload_head_range_and_delete(object_store):
    content = b"0123456789" * 20
    stored = await object_store.put_object(
        uuid4(), ObjectSuffix.BINARY, chunks(content), max_bytes=len(content)
    )
    assert stored.size == len(content)
    assert await object_store.exists(stored.key)
    response = await object_store.get_range(stored.key, 7, 31)
    assert b"".join([bytes(part) async for part in response.body]) == content[7:31]
    assert response.byte_range == (7, 31)
    assert await object_store.delete(stored.key)
    assert not await object_store.exists(stored.key)


@pytest.mark.anyio
async def test_equal_concurrent_uploads_have_independent_keys(object_store):
    content = b"same immutable content" * 10_000
    first, second = await asyncio.gather(
        object_store.put_object(
            uuid4(), ObjectSuffix.BINARY, chunks(content), max_bytes=len(content)
        ),
        object_store.put_object(
            uuid4(), ObjectSuffix.BINARY, chunks(content), max_bytes=len(content)
        ),
    )
    assert first.key != second.key
    await object_store.delete(first.key)
    assert await object_store.exists(second.key)


@pytest.mark.anyio
async def test_materialize_opens_with_pymupdf(object_store):
    document = pymupdf.open()
    document.new_page()
    pdf = document.tobytes()
    document.close()
    stored = await object_store.put_object(
        uuid4(), ObjectSuffix.PDF, pdf, max_bytes=len(pdf), required_prefix=b"%PDF-"
    )
    async with object_store.materialize(stored.key) as path:
        with pymupdf.open(path) as materialized:
            assert materialized.page_count == 1


@pytest.mark.anyio
async def test_cancelled_owned_upload_cleans_temporary_input(object_store, tmp_path, monkeypatch):
    started = asyncio.Event()

    async def blocked():
        started.set()
        yield b"partial"
        await asyncio.Event().wait()

    real_mkstemp = tempfile.mkstemp

    def task_mkstemp(*, prefix, suffix=""):
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=tmp_path)

    monkeypatch.setattr("quirebase.core.storage.tempfile.mkstemp", task_mkstemp)
    task = asyncio.create_task(
        object_store.put_object(uuid4(), ObjectSuffix.BINARY, blocked(), max_bytes=100)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.glob("quirebase-object-*"))
