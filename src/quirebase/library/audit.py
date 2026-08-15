from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from quirebase.models import AuditEvent

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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
