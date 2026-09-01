from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import UploadFile


async def upload_chunks(upload: UploadFile, chunk_size: int = 1024 * 1024) -> AsyncIterator[bytes]:
    while chunk := await upload.read(chunk_size):
        yield chunk
