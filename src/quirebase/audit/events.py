from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from quirebase.access.authorization import SystemAction, require_system_action
from quirebase.audit.invocations import current_programmatic_invocation
from quirebase.models import AuditEvent

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


def record_event(
    db: AsyncSession,
    actor_id: UUID | None,
    action: str,
    target_type: str,
    target_id: UUID | str | None = None,
    detail: dict[str, Any] | str | None = None,
    *,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    target_ids: list[UUID] | tuple[UUID, ...] | None = None,
    authorization_role: str | None = None,
    authorization_resource_action: str | None = None,
    result: str = "succeeded",
    source: str | None = None,
) -> AuditEvent:
    invocation = current_programmatic_invocation()
    if invocation is not None:
        if isinstance(detail, dict):
            detail = {**detail, "invocation": invocation.detail()}
        elif isinstance(detail, str):
            detail = {"message": detail, "invocation": invocation.detail()}
        else:
            detail = {"invocation": invocation.detail()}
    detail_text: str | None = None
    if isinstance(detail, dict):
        detail_text = json.dumps(detail, ensure_ascii=False, default=str)
    elif isinstance(detail, str):
        detail_text = detail
    event = AuditEvent(
        actor_id=actor_id,
        workspace_id=workspace_id,
        project_id=project_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail_text,
        target_ids=json.dumps([str(target_id) for target_id in target_ids])
        if target_ids is not None
        else None,
        authorization_role=authorization_role,
        authorization_resource_action=authorization_resource_action,
        result=result,
        source=source or (invocation.protocol if invocation is not None else "internal"),
    )
    db.add(event)
    return event


async def query_events(
    db: AsyncSession,
    admin: User,
    actor_id: UUID | None = None,
    action: str | None = None,
    target_type: str | None = None,
    search: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEvent], int]:
    await require_system_action(db, admin, SystemAction.audit_read)
    query = select(AuditEvent)
    count_query = select(func.count(AuditEvent.id))
    filters = []
    if actor_id:
        filters.append(AuditEvent.actor_id == actor_id)
    if action:
        filters.append(AuditEvent.action == action)
    if target_type:
        filters.append(AuditEvent.target_type == target_type)
    if search.strip():
        term = f"%{search.strip()}%"
        filters.append(
            or_(
                AuditEvent.action.ilike(term),
                AuditEvent.target_type.ilike(term),
                AuditEvent.target_id.ilike(term),
                AuditEvent.detail.ilike(term),
            )
        )
    if filters:
        query = query.where(*filters)
        count_query = count_query.where(*filters)
    total = await db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    events = list(
        (
            await db.scalars(
                query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(page_size)
            )
        ).all()
    )
    return events, total
