from __future__ import annotations

import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import BinaryIO

from .config import Settings, get_settings


class LocalObjectStore:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def path(self, object_key: str) -> Path:
        candidate = (self.settings.object_dir / object_key).resolve()
        root = self.settings.object_dir.resolve()
        if root not in candidate.parents:
            raise ValueError("invalid object key")
        return candidate

    def put_pdf(self, source: BinaryIO, maximum: int) -> tuple[str, str, int]:
        key, sha256, size, temporary = self._stage(source, maximum)
        with temporary.open("rb") as check:
            if check.read(5) != b"%PDF-":
                temporary.unlink(missing_ok=True)
                raise ValueError("file is not a PDF")
        return self._finish(temporary, key + ".pdf", sha256, size)

    def put_attachment(self, source: BinaryIO, maximum: int) -> tuple[str, str, int]:
        key, sha256, size, temporary = self._stage(source, maximum)
        return self._finish(temporary, key + ".bin", sha256, size)

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
