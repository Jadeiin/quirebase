from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import anyio
from filelock import FileLock, Timeout
from obstore.exceptions import BaseError as ObstoreError
from obstore.store import LocalStore, S3Store

from quirebase.core.config import Settings, get_settings

if TYPE_CHECKING:
    from datetime import datetime

    from obstore import GetOptions, ObjectMeta
    from obstore.store import ObjectStore as ObstoreDataPlane

type ObjectSource = Path | bytes | AsyncIterable[bytes]


def _temporary_path(*, prefix: str, suffix: str = "") -> Path:
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(descriptor)
    return Path(name)


@dataclass(frozen=True)
class ObjectMetadata:
    key: str
    size: int
    etag: str | None
    last_modified: datetime


@dataclass(frozen=True)
class ObjectResponse:
    metadata: ObjectMetadata
    byte_range: tuple[int, int]
    body: AsyncIterable[bytes]


@dataclass
class _LocalLease:
    marker: Path
    lock: FileLock = field(repr=False)
    released: bool = field(default=False, init=False)

    def release(self) -> None:
        if self.released:
            return
        self.lock.release()
        self.marker.unlink(missing_ok=True)
        self.released = True


@dataclass
class StagedObject:
    key: str
    sha256: str
    size: int
    _lease: _LocalLease | None = field(default=None, repr=False)

    async def release(self) -> None:
        if self._lease is not None:
            await asyncio.to_thread(self._lease.release)


def _metadata(value: ObjectMeta) -> ObjectMetadata:
    return ObjectMetadata(
        key=value["path"],
        size=value["size"],
        etag=value.get("e_tag"),
        last_modified=value["last_modified"],
    )


async def _path_chunks(path: Path, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    source = await anyio.open_file(path, "rb")
    try:
        while chunk := await source.read(chunk_size):
            yield chunk
    finally:
        await source.aclose()


def _consume_current_cancellation() -> None:
    task = asyncio.current_task()
    if task is not None:
        task.uncancel()


async def _finish_task_despite_cancellation[Result](task: asyncio.Task[Result]) -> Result:
    while True:
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            _consume_current_cancellation()


async def _acquire_cleanup_lock(lock: FileLock) -> None:
    """Acquire an independent file lock without blocking the event loop indefinitely."""
    while True:
        acquisition = asyncio.create_task(asyncio.to_thread(lock.acquire, timeout=0.1))
        try:
            await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            _consume_current_cancellation()
            try:
                await _finish_task_despite_cancellation(acquisition)
            except Timeout:
                pass
            else:
                release = asyncio.create_task(asyncio.to_thread(lock.release))
                await _finish_task_despite_cancellation(release)
            raise
        except Timeout:
            await asyncio.sleep(0)
        else:
            return


class ObjectStore:
    """Quirebase's object-storage seam, backed by an obstore data plane."""

    def __init__(self, store: ObstoreDataPlane, *, local_root: Path | None = None):
        self._store = store
        self._local_root = local_root.resolve() if local_root is not None else None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ObjectStore:
        effective = settings or get_settings()
        if effective.object_store == "local":
            root = effective.object_dir
            return cls(LocalStore(root, mkdir=True, automatic_cleanup=True), local_root=root)
        if not effective.s3_bucket:
            raise ValueError("QUIREBASE_S3_BUCKET is required for S3 object storage")
        client_options: dict[str, Any] = {"timeout": "5m"}
        if effective.s3_endpoint and effective.s3_endpoint.startswith("http://"):
            client_options["allow_http"] = True
        s3_options: dict[str, Any] = {"client_options": client_options}
        if effective.s3_region:
            s3_options["region"] = effective.s3_region
        if effective.s3_endpoint:
            s3_options["endpoint"] = effective.s3_endpoint
            s3_options["virtual_hosted_style_request"] = False
        if prefix := (effective.s3_prefix or "").strip("/"):
            s3_options["prefix"] = prefix
        return cls(S3Store(effective.s3_bucket, **s3_options))

    @property
    def is_local(self) -> bool:
        return self._local_root is not None

    async def put(self, key: str, source: ObjectSource) -> ObjectMetadata:
        self._validate_key(key)
        await self._store.put_async(key, source, mode="overwrite")
        return _metadata(await self._store.head_async(key))

    async def put_cas(
        self,
        source: ObjectSource,
        *,
        suffix: str,
        max_bytes: int,
        required_prefix: bytes | None = None,
    ) -> StagedObject:
        temporary = _temporary_path(prefix="quirebase-cas-")
        digest = hashlib.sha256()
        size = 0
        prefix = bytearray()
        lease: _LocalLease | None = None
        try:
            async with await anyio.open_file(temporary, "wb") as target:
                async for chunk in self._source_chunks(source):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("file exceeds configured size limit")
                    if required_prefix is not None and len(prefix) < len(required_prefix):
                        prefix.extend(chunk[: len(required_prefix) - len(prefix)])
                    digest.update(chunk)
                    await target.write(chunk)
            if required_prefix is not None and bytes(prefix) != required_prefix:
                raise ValueError("file content does not match the required format")
            sha256 = digest.hexdigest()
            key = f"{sha256[:2]}/{sha256[2:4]}/{sha256}{suffix}"
            if self._local_root is not None:
                cleanup_lock = self._cleanup_lock(key)
                await _acquire_cleanup_lock(cleanup_lock)
                try:
                    lease = await asyncio.to_thread(self._acquire_local_lease, key)
                    await self._store.put_async(key, temporary, mode="overwrite")
                finally:
                    await asyncio.to_thread(cleanup_lock.release)
            else:
                # CAS objects are immutable. Identical concurrent uploads may atomically
                # overwrite the same bytes so multipart remains available.
                # Size and digest are already known, so a second HEAD would only add a
                # failure window after the atomic publish.
                await self._store.put_async(key, temporary, mode="overwrite")
            return StagedObject(key=key, sha256=sha256, size=size, _lease=lease)
        except BaseException:
            if lease is not None:
                await asyncio.to_thread(lease.release)
            raise
        finally:
            await asyncio.shield(asyncio.to_thread(temporary.unlink, missing_ok=True))

    async def head(self, key: str) -> ObjectMetadata:
        self._validate_key(key)
        return _metadata(await self._store.head_async(key))

    async def exists(self, key: str) -> bool:
        try:
            await self.head(key)
        except (FileNotFoundError, ObstoreError) as error:
            if isinstance(error, FileNotFoundError) or type(error).__name__ == "NotFoundError":
                return False
            raise
        return True

    async def get(
        self,
        key: str,
        *,
        byte_range: tuple[int, int] | None = None,
        chunk_size: int | None = None,
    ) -> ObjectResponse:
        self._validate_key(key)
        options: GetOptions | None = None
        if byte_range is not None:
            options = {"range": byte_range}
        result = await self._store.get_async(key, options=options)
        body = result.stream(min_chunk_size=chunk_size) if chunk_size else result
        return ObjectResponse(
            metadata=_metadata(result.meta),
            byte_range=result.range,
            body=body,
        )

    async def get_range(
        self, key: str, start: int, end: int, *, chunk_size: int | None = None
    ) -> ObjectResponse:
        """Read the half-open byte range ``[start, end)``."""
        if start < 0 or end <= start:
            raise ValueError("invalid object range")
        return await self.get(key, byte_range=(start, end), chunk_size=chunk_size)

    async def delete(self, key: str) -> bool:
        self._validate_key(key)
        if self._local_root is None:
            try:
                await self._store.delete_async(key)
            except (FileNotFoundError, ObstoreError) as error:
                if not (
                    isinstance(error, FileNotFoundError) or type(error).__name__ == "NotFoundError"
                ):
                    raise
            return True
        cleanup_lock = self._cleanup_lock(key)
        await _acquire_cleanup_lock(cleanup_lock)
        try:
            if await asyncio.to_thread(self._has_active_local_lease, key):
                return False
            with suppress(FileNotFoundError):
                await self._store.delete_async(key)
            return True
        finally:
            await asyncio.to_thread(cleanup_lock.release)

    @asynccontextmanager
    async def materialize(self, key: str) -> AsyncIterator[Path]:
        self._validate_key(key)
        if self._local_root is not None:
            path = self._local_path(key)
            if not await asyncio.to_thread(path.is_file):
                raise FileNotFoundError(key)
            yield path
            return
        temporary = _temporary_path(prefix="quirebase-object-", suffix=Path(key).suffix)
        try:
            response = await self.get(key)
            async with await anyio.open_file(temporary, "wb") as target:
                async for chunk in response.body:
                    await target.write(chunk)
            yield temporary
        finally:
            await asyncio.shield(asyncio.to_thread(temporary.unlink, missing_ok=True))

    async def iter_prefix(self, prefix: str) -> AsyncIterator[ObjectMetadata]:
        async for batch in self._store.list(prefix.strip("/") or None):
            for item in batch:
                yield _metadata(item)

    async def _source_chunks(self, source: ObjectSource) -> AsyncIterator[bytes]:
        if isinstance(source, bytes):
            yield source
        elif isinstance(source, Path):
            async for chunk in _path_chunks(source):
                yield chunk
        else:
            async for chunk in source:
                if chunk:
                    yield bytes(chunk)

    @staticmethod
    def _validate_key(key: str) -> None:
        if not key or key.startswith("/") or ".." in Path(key).parts:
            raise ValueError("invalid object key")

    def _local_path(self, key: str) -> Path:
        assert self._local_root is not None
        candidate = (self._local_root / key).resolve()
        if self._local_root not in candidate.parents:
            raise ValueError("invalid object key")
        return candidate

    def _lock_root(self) -> Path:
        assert self._local_root is not None
        return self._local_root / ".locks"

    @staticmethod
    def _lock_name(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _cleanup_lock(self, key: str) -> FileLock:
        self._validate_key(key)
        root = self._lock_root()
        root.mkdir(parents=True, exist_ok=True)
        return FileLock(
            root / f"{self._lock_name(key)[:2]}.cleanup.lock",
            thread_local=False,
        )

    def _acquire_local_lease(self, key: str) -> _LocalLease:
        root = self._lock_root()
        root.mkdir(parents=True, exist_ok=True)
        marker = root / f"{self._lock_name(key)}.{uuid4().hex}.lease.lock"
        lock = FileLock(marker, thread_local=False)
        lock.acquire()
        return _LocalLease(marker, lock)

    def _has_active_local_lease(self, key: str) -> bool:
        root = self._lock_root()
        if not root.is_dir():
            return False
        active = False
        for marker in root.glob(f"{self._lock_name(key)}.*.lease.lock"):
            probe = FileLock(marker, thread_local=False)
            try:
                probe.acquire(blocking=False)
            except Timeout:
                active = True
            else:
                probe.release()
                marker.unlink(missing_ok=True)
        return active


@lru_cache
def get_object_store() -> ObjectStore:
    return ObjectStore.from_settings()
