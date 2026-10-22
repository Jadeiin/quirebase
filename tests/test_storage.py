import asyncio
import hashlib
import os
from uuid import UUID, uuid4

import pymupdf
import pytest
from advanced_alchemy.types import FileObject

from quirebase.core.config import Settings
from quirebase.core.storage import (
    ObjectStore,
    ObjectSuffix,
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
    assert stored.checksum == f"sha256:{hashlib.sha256(content).hexdigest()}"
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
            uuid4(), ObjectSuffix.BINARY, chunks(content, 4096), max_bytes=len(content)
        ),
        object_store.put_object(
            uuid4(), ObjectSuffix.BINARY, chunks(content, 4096), max_bytes=len(content)
        ),
    )
    assert first.key != second.key
    assert first.checksum == second.checksum
    await object_store.delete(first.key)
    assert await object_store.exists(second.key)


@pytest.mark.anyio
@pytest.mark.parametrize("suffix", ObjectSuffix)
async def test_upload_checksums_one_shot_stream_without_readback_or_temporary_file(
    object_store, monkeypatch, suffix
):
    content = b"streamed content\x00\xff" * 1000

    class OneShotSource:
        iterations = 0

        def __aiter__(self):
            assert self.iterations == 0, "the upload source must only be consumed once"
            self.iterations += 1
            return self.iter_chunks()

        async def iter_chunks(self):
            yield b""
            async for chunk in chunks(content, 19):
                yield chunk

    def unexpected_materialization(*args, **kwargs):
        pytest.fail("upload checksum must not materialize or reread the object")

    source = OneShotSource()
    with monkeypatch.context() as patch:
        patch.setattr("quirebase.core.storage._temporary_path", unexpected_materialization)
        patch.setattr(ObjectStore, "get", unexpected_materialization)
        stored = await object_store.put_object(uuid4(), suffix, source, max_bytes=len(content))
    assert source.iterations == 1
    assert stored.size == len(content)
    assert stored.checksum == f"sha256:{hashlib.sha256(content).hexdigest()}"
    response = await object_store.get(stored.key)
    assert b"".join([bytes(part) async for part in response.body]) == content


@pytest.mark.anyio
async def test_upload_checksum_is_independent_of_source_and_chunk_boundaries(
    object_store, tmp_path
):
    content = b"same uploaded bytes" * 23
    source = tmp_path / "source.bin"
    source.write_bytes(content)
    receipts = [
        await object_store.put_object(uuid4(), ObjectSuffix.BINARY, value, max_bytes=len(content))
        for value in (content, source, chunks(content, 1), chunks(content, 97))
    ]
    assert {receipt.checksum for receipt in receipts} == {
        f"sha256:{hashlib.sha256(content).hexdigest()}"
    }
    assert len({receipt.key for receipt in receipts}) == len(receipts)


@pytest.mark.anyio
@pytest.mark.parametrize("object_store", ["local"], indirect=True)
async def test_empty_upload_has_standard_sha256_checksum(object_store):
    stored = await object_store.put_object(uuid4(), ObjectSuffix.BINARY, chunks(b""), max_bytes=0)
    assert stored.size == 0
    assert stored.checksum == (
        "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


@pytest.mark.anyio
@pytest.mark.parametrize("source_kind", ["stream", "path"])
async def test_upload_closes_source_when_backend_rejects_after_consumption(
    object_store, monkeypatch, tmp_path, source_kind
):
    closed = asyncio.Event()

    async def source_chunks():
        try:
            await asyncio.sleep(0)
            yield b"streamed content"
        finally:
            closed.set()

    async def reject(self, data, **kwargs):
        assert await anext(data) == b"streamed content"
        await asyncio.sleep(0)
        raise RuntimeError("backend rejected upload")

    monkeypatch.setattr(FileObject, "save_async", reject)
    if source_kind == "path":
        source = tmp_path / "source.bin"
        monkeypatch.setattr("quirebase.core.storage._path_chunks", lambda path: source_chunks())
    else:
        source = source_chunks()
    with pytest.raises(RuntimeError, match="backend rejected upload"):
        await object_store.put_object(uuid4(), ObjectSuffix.BINARY, source, max_bytes=100)
    assert closed.is_set()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content", "max_bytes", "required_prefix", "error"),
    [
        (b"%PDF-contents", 6, b"%PDF-", "file exceeds configured size limit"),
        (b"%PDX-contents", 100, b"%PDF-", "file content does not match the required format"),
    ],
)
async def test_rejected_streamed_upload_cleans_owned_object(
    object_store, content, max_bytes, required_prefix, error
):
    object_id = uuid4()
    with pytest.raises(ValueError, match=error):
        await object_store.put_object(
            object_id,
            ObjectSuffix.PDF,
            chunks(content, 2),
            max_bytes=max_bytes,
            required_prefix=required_prefix,
        )
    assert not await object_store.exists(object_key(object_id, ObjectSuffix.PDF))


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
async def test_cancelled_owned_upload_cleans_partial_object(object_store):
    object_id = uuid4()
    key = object_key(object_id, ObjectSuffix.BINARY)
    started = asyncio.Event()

    async def blocked():
        started.set()
        yield b"partial"
        await asyncio.Event().wait()

    task = asyncio.create_task(
        object_store.put_object(object_id, ObjectSuffix.BINARY, blocked(), max_bytes=100)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await object_store.exists(key)
