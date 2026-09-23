from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from inquiro import SearchClause, SearchQuery

from quirebase.access.workspaces import require_workspace_membership
from quirebase.core.errors import ResourceUnavailable
from quirebase.library.activity import (
    get_matching_accessible_item_identifiers,
    record_discovery_search_audit,
)
from quirebase.library.providers import search_candidates
from quirebase.models import User

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.core.config import Settings


@dataclass(frozen=True)
class DiscoveryClause:
    field: str
    operator: str
    term: str


@dataclass(frozen=True)
class CandidateView:
    provider: str
    identifier_provider: str
    identifier: str
    title: str
    authors: str | None = None
    publication_title: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    abstract: str | None = None
    imported: bool = False


@dataclass(frozen=True)
class CandidatePageView:
    provider: str
    results: tuple[CandidateView, ...]
    total: int
    page: int
    per_page: int


async def search_candidate_records(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    provider: str,
    clauses: tuple[DiscoveryClause, ...],
    *,
    page: int = 1,
    per_page: int = 10,
    sort: str = "relevance",
    year_from: int | None = None,
    year_to: int | None = None,
    settings: Settings,
) -> CandidatePageView:
    user_id = user.id
    # Authentication and settings reads may have opened a short transaction;
    # do not keep that transaction alive while the Provider performs network I/O.
    await db.rollback()
    result = await search_candidates(
        SearchQuery(
            provider=provider,
            clauses=tuple(
                SearchClause(clause.field, clause.operator, clause.term) for clause in clauses
            ),
            page=page,
            per_page=per_page,
            sort=sort,
            year_from=year_from,
            year_to=year_to,
        ),
        settings,
    )
    reloaded_user = await db.get(User, user_id)
    if reloaded_user is None or not reloaded_user.active:
        raise ResourceUnavailable("user not available")
    reloaded_user = (await require_workspace_membership(db, reloaded_user, workspace_id)).actor
    candidate_identifiers = {
        (candidate.identifier.provider, candidate.identifier.value) for candidate in result.results
    }
    candidate_identifiers.update(
        ("doi", candidate.doi) for candidate in result.results if candidate.doi
    )
    accessible_identifiers = await get_matching_accessible_item_identifiers(
        db, reloaded_user, workspace_id, candidate_identifiers
    )
    page_view = CandidatePageView(
        provider=result.provider,
        results=tuple(
            CandidateView(
                provider=candidate.provider,
                identifier_provider=candidate.identifier.provider,
                identifier=candidate.identifier.value,
                title=candidate.title,
                authors=candidate.authors,
                publication_title=candidate.publication_title,
                publication_date=candidate.publication_date,
                doi=candidate.doi,
                abstract=candidate.abstract,
                imported=(
                    (
                        candidate.identifier.provider.casefold(),
                        candidate.identifier.value.casefold(),
                    )
                    in accessible_identifiers
                    or bool(
                        candidate.doi
                        and ("doi", candidate.doi.casefold()) in accessible_identifiers
                    )
                ),
            )
            for candidate in result.results
        ),
        total=result.total,
        page=result.page,
        per_page=result.per_page,
    )
    await record_discovery_search_audit(
        db, reloaded_user, workspace_id, provider, clauses, len(page_view.results)
    )
    return page_view
