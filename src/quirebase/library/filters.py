from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class AuthorFilter:
    last_name: str
    first_name: str | None = None


@dataclass(frozen=True)
class LibraryFilter:
    q: str = ""
    tag: UUID | None = None
    project: UUID | None = None
    year: str = ""
    keyword: str = ""
    author: str = ""
    has_files: bool | None = None
    has_tags: bool | None = None
    has_projects: bool | None = None
    reference_type: str | None = None
    keyword_exact: str | None = None
    authors: tuple[AuthorFilter, ...] = ()
    publication_title: str | None = None
    import_batch: UUID | None = None
