from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from quirebase.core.config import get_settings
from quirebase.core.storage import get_object_store

if TYPE_CHECKING:
    from collections.abc import AsyncIterable
    from pathlib import Path


async def put_pdf_object(content: bytes, maximum: int = 100_000) -> tuple[str, str, int]:
    staged = await get_object_store().put_cas(
        content,
        suffix=".pdf",
        max_bytes=maximum,
        required_prefix=b"%PDF-",
    )
    await staged.release()
    return staged.key, staged.sha256, staged.size


def local_object_path(key: str) -> Path:
    return get_settings().object_dir / key


async def collect_body(body: AsyncIterable[bytes]) -> BytesIO:
    value = BytesIO()
    async for chunk in body:
        value.write(chunk)
    value.seek(0)
    return value
