from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SearchIndex(Protocol):
    def index_item(self, db: Session, item_id: str) -> None: ...

    def remove_item(self, db: Session, item_id: str) -> None: ...

    def search(self, db: Session, query: str, limit: int = 200) -> list[str]: ...
