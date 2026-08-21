from __future__ import annotations

import json
from typing import TYPE_CHECKING

from quirebase.access.items import visible_items_query
from quirebase.audit import record_event

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.discovery.search import SearchClause
    from quirebase.models import User


def record_discovery_search_audit(
    db: Session,
    user: User,
    provider: str,
    clauses: list[SearchClause],
    result_count: int,
) -> None:
    record_event(
        db,
        user.id,
        "metadata.search",
        "provider",
        provider,
        detail={
            "fields": [clause.field for clause in clauses],
            "result_count": result_count,
        },
    )
    db.commit()


def get_accessible_item_identifiers(db: Session, user: User) -> set[tuple[str, str]]:
    identifiers_by_provider: set[tuple[str, str]] = set()
    for item in db.scalars(visible_items_query(user)).all():
        if item.doi:
            identifiers_by_provider.add(("doi", item.doi.casefold()))
        try:
            identifiers = json.loads(item.identifiers or "{}")
        except json.JSONDecodeError:
            identifiers = {}
        for key, value in identifiers.items():
            if value:
                identifiers_by_provider.add((str(key), str(value).casefold()))
    return identifiers_by_provider
