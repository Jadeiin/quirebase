from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO
from uuid import uuid4

from filelock import FileLock, Timeout

from quirebase.core.config import Settings, get_settings


@dataclass
class ObjectLease:
    """An in-flight reference that keeps a content-addressed object alive."""

    marker: Path
    _lock: FileLock = field(repr=False)
    _released: bool = field(default=False, init=False, repr=False)

    def release(self) -> None:
        if self._released:
            return
        self._lock.release()
        self.marker.unlink(missing_ok=True)
        self._released = True

    def __del__(self) -> None:
        self.release()


class LocalObjectStore:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def path(self, object_key: str) -> Path:
        candidate = (self.settings.object_dir / object_key).resolve()
        root = self.settings.object_dir.resolve()
        if root not in candidate.parents:
            raise ValueError("invalid object key")
        return candidate

    def delete(self, object_key: str) -> None:
        path = self.path(object_key)
        path.unlink(missing_ok=True)
        root = self.settings.object_dir.resolve()
        for directory in (path.parent, path.parent.parent):
            if directory == root:
                break
            try:
                directory.rmdir()
            except OSError:
                break

    def cleanup_lock(self, object_key: str) -> FileLock:
        lock_root = self._lock_root(object_key)
        lock_root.mkdir(parents=True, exist_ok=True)
        return FileLock(lock_root / f"{self._lock_name(object_key)[:2]}.cleanup.lock")

    def has_active_lease(self, object_key: str) -> bool:
        """Return whether a writer has not yet committed its object reference.

        The caller must hold ``cleanup_lock(object_key)`` so a new lease cannot
        appear between this check and physical deletion.
        """
        lock_root = self._lock_root(object_key)
        if not lock_root.is_dir():
            return False
        active = False
        for marker in lock_root.glob(f"{self._lock_name(object_key)}.*.lease.lock"):
            probe = FileLock(marker)
            try:
                probe.acquire(blocking=False)
            except Timeout:
                active = True
            else:
                probe.release()
                marker.unlink(missing_ok=True)
        return active

    def put_pdf(self, source: BinaryIO, maximum: int) -> tuple[str, str, int]:
        key, sha256, size, temporary = self._stage(source, maximum)
        with temporary.open("rb") as check:
            header = check.read(5)
        if header != b"%PDF-":
            temporary.unlink(missing_ok=True)
            raise ValueError("file is not a PDF")
        return self._finish(temporary, key + ".pdf", sha256, size)

    def put_staged_pdf(self, source: BinaryIO, maximum: int) -> tuple[str, str, int, ObjectLease]:
        key, sha256, size, temporary = self._stage(source, maximum)
        with temporary.open("rb") as check:
            header = check.read(5)
        if header != b"%PDF-":
            temporary.unlink(missing_ok=True)
            raise ValueError("file is not a PDF")

        object_key = key + ".pdf"
        try:
            with self.cleanup_lock(object_key):
                lease = self._acquire_lease(object_key)
                key, sha256, size = self._finish(temporary, object_key, sha256, size)
        except Exception:
            temporary.unlink(missing_ok=True)
            if "lease" in locals():
                lease.release()
            raise
        return key, sha256, size, lease

    def put_attachment(self, source: BinaryIO, maximum: int) -> tuple[str, str, int]:
        key, sha256, size, temporary = self._stage(source, maximum)
        return self._finish(temporary, key + ".bin", sha256, size)

    def put_staged_attachment(
        self, source: BinaryIO, maximum: int
    ) -> tuple[str, str, int, ObjectLease]:
        key, sha256, size, temporary = self._stage(source, maximum)
        object_key = key + ".bin"
        try:
            with self.cleanup_lock(object_key):
                lease = self._acquire_lease(object_key)
                key, sha256, size = self._finish(temporary, object_key, sha256, size)
        except Exception:
            temporary.unlink(missing_ok=True)
            if "lease" in locals():
                lease.release()
            raise
        return key, sha256, size, lease

    def _stage(self, source: BinaryIO, maximum: int) -> tuple[str, str, int, Path]:
        self.settings.object_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with NamedTemporaryFile(dir=self.settings.object_dir, delete=False) as target:
            temporary = Path(target.name)
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    target.close()
                    temporary.unlink(missing_ok=True)
                    raise ValueError("file exceeds configured size limit")
                digest.update(chunk)
                target.write(chunk)
        sha256 = digest.hexdigest()
        key = f"{sha256[:2]}/{sha256[2:4]}/{sha256}"
        return key, sha256, size, temporary

    def _finish(self, temporary: Path, key: str, sha256: str, size: int) -> tuple[str, str, int]:
        final = self.path(key)
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            temporary.unlink()
        else:
            os.replace(temporary, final)
        return key, sha256, size

    def _lock_root(self, object_key: str) -> Path:
        self.path(object_key)
        return self.settings.object_dir / ".locks"

    @staticmethod
    def _lock_name(object_key: str) -> str:
        return hashlib.sha256(object_key.encode()).hexdigest()

    def _acquire_lease(self, object_key: str) -> ObjectLease:
        lock_root = self._lock_root(object_key)
        lock_root.mkdir(parents=True, exist_ok=True)
        marker = lock_root / f"{self._lock_name(object_key)}.{uuid4().hex}.lease.lock"
        lock = FileLock(marker)
        lock.acquire()
        return ObjectLease(marker, lock)
