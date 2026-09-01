from __future__ import annotations

import os
import re
import tempfile
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import anyio
from obstore.exceptions import BaseError as ObstoreError
from obstore.store import LocalStore, S3Store

from quirebase.core.config import Settings, get_settings

if TYPE_CHECKING:
    from datetime import datetime

    from obstore import GetOptions, ObjectMeta
    from obstore.store import ObjectStore as ObstoreDataPlane

type ObjectSource = Path | bytes | AsyncIterable[bytes]


class ObjectSuffix(StrEnum):
    PDF = ".pdf"
    BINARY = ".bin"
    PNG = ".png"


_MANAGED_OBJECT_RE = re.compile(
    r"^(?P<a>[0-9a-f]{2})/(?P<b>[0-9a-f]{2})/(?P<id>[0-9a-f]{32})(?P<suffix>\.pdf|\.bin|\.png)$"
)
_LEGACY_CAS_RE = re.compile(
    r"^(?:[0-9a-f]{2}/[0-9a-f]{2}/)?(?P<digest>[0-9a-f]{64})(?:\.[a-z0-9]+)?$"
)


def object_key(object_id: UUID, suffix: ObjectSuffix) -> str:
    """Return the only supported key layout for a managed object."""
    encoded = object_id.hex
    return f"{encoded[:2]}/{encoded[2:4]}/{encoded}{suffix.value}"


def managed_object_id(key: str) -> UUID | None:
    match = _MANAGED_OBJECT_RE.fullmatch(key)
    if match is None or key[:2] != match["id"][:2] or key[3:5] != match["id"][2:4]:
        return None
    return UUID(hex=match["id"])


def is_managed_object_key(key: str) -> bool:
    return managed_object_id(key) is not None


def is_legacy_cas_key(key: str) -> bool:
    return _LEGACY_CAS_RE.fullmatch(key) is not None and not is_managed_object_key(key)


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


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int


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
        """Write an explicit non-business key (used by probes and migrations)."""
        self._validate_key(key)
        await self._store.put_async(key, source, mode="overwrite")
        return _metadata(await self._store.head_async(key))

    async def put_object(
        self,
        object_id: UUID,
        suffix: ObjectSuffix,
        source: ObjectSource,
        *,
        max_bytes: int,
        required_prefix: bytes | None = None,
    ) -> StoredObject:
        """Stream bytes directly to a preallocated owned key."""
        key = object_key(object_id, suffix)
        size = 0
        prefix = bytearray()

        async def checked_chunks() -> AsyncIterator[bytes]:
            nonlocal size
            async for chunk in self._source_chunks(source):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("file exceeds configured size limit")
                if required_prefix is not None and len(prefix) < len(required_prefix):
                    prefix.extend(chunk[: len(required_prefix) - len(prefix)])
                yield chunk

        try:
            await self._store.put_async(key, checked_chunks(), mode="overwrite")
            if required_prefix is not None and bytes(prefix) != required_prefix:
                raise ValueError("file content does not match the required format")
            return StoredObject(key=key, size=size)
        except BaseException:
            with suppress(Exception):
                await self._store.delete_async(key)
            raise

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
        return ObjectResponse(metadata=_metadata(result.meta), byte_range=result.range, body=body)

    async def get_range(
        self, key: str, start: int, end: int, *, chunk_size: int | None = None
    ) -> ObjectResponse:
        if start < 0 or end <= start:
            raise ValueError("invalid object range")
        return await self.get(key, byte_range=(start, end), chunk_size=chunk_size)

    async def delete(self, key: str) -> bool:
        self._validate_key(key)
        if not await self.exists(key):
            return False
        with suppress(FileNotFoundError):
            await self._store.delete_async(key)
        return True

    @asynccontextmanager
    async def materialize(self, key: str) -> AsyncIterator[Path]:
        self._validate_key(key)
        if self._local_root is not None:
            path = self._local_path(key)
            if not await anyio.to_thread.run_sync(path.is_file):
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
            await anyio.to_thread.run_sync(lambda: temporary.unlink(missing_ok=True))

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


@lru_cache
def get_object_store() -> ObjectStore:
    return ObjectStore.from_settings()
