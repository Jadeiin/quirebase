from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from quirebase.audit import record_event

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


class SearchClauseView(Protocol):
    @property
    def field(self) -> str: ...


async def record_discovery_search_audit(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    provider: str,
    clauses: Sequence[SearchClauseView],
    result_count: int,
) -> None:
    record_event(
        db,
        user.id,
        "metadata.search",
        "provider",
        provider,
        workspace_id=workspace_id,
        detail={
            "fields": [clause.field for clause in clauses],
            "result_count": result_count,
        },
    )
    await db.commit()
