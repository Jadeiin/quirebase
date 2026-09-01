from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING
from uuid import uuid4

from quirebase.core.config import get_settings
from quirebase.core.storage import ObjectSuffix, get_object_store

if TYPE_CHECKING:
    from collections.abc import AsyncIterable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import FileRevision, User


async def put_pdf_object(content: bytes, maximum: int = 100_000) -> tuple[str, int]:
    staged = await get_object_store().put_object(
        uuid4(),
        ObjectSuffix.PDF,
        content,
        max_bytes=maximum,
        required_prefix=b"%PDF-",
    )
    return staged.key, staged.size


async def store_ready_pdf_revision(
    db: AsyncSession, user: User, item_id: str, content: bytes, filename: str
) -> FileRevision:
    from quirebase.models import FileRevision

    key, size = await put_pdf_object(content, max(len(content), 100_000))
    revision = FileRevision(
        item_id=item_id,
        object_key=key,
        size=size,
        original_name=filename,
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    await db.flush()
    return revision


def local_object_path(key: str) -> Path:
    return get_settings().object_dir / key


async def collect_body(body: AsyncIterable[bytes]) -> BytesIO:
    value = BytesIO()
    async for chunk in body:
        value.write(chunk)
    value.seek(0)
    return value
