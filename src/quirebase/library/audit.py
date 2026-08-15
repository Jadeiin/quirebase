from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, or_, select

from quirebase.core.errors import ResourceUnavailable
from quirebase.models import AuditEvent

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import User


def record_audit_event(
    db: Session,
    actor_id: str | None,
    action: str,
    target_type: str,
    target_id: str | None = None,
    detail: dict[str, Any] | str | None = None,
) -> AuditEvent:
    detail_str: str | None = None
    if isinstance(detail, dict):
        detail_str = json.dumps(detail, ensure_ascii=False)
    elif isinstance(detail, str):
        detail_str = detail
    event = AuditEvent(
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=detail_str,
    )
    db.add(event)
    return event


def query_audit_events(
    db: Session,
    admin: User,
    actor_id: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
    search: str = "",
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditEvent], int]:
    if admin.role != "administrator":
        raise ResourceUnavailable("administrator required")
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
    total = db.scalar(count_query) or 0
    offset = max(0, (page - 1) * page_size)
    events = list(
        db.scalars(
            query.order_by(AuditEvent.created_at.desc()).offset(offset).limit(page_size)
        ).all()
    )
    return events, total
