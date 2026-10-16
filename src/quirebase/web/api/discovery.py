from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from quirebase.library import (
    CandidatePageView,
    MetadataProviderChoices,
    get_metadata_provider_choices,
    search_candidate_records,
)
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.discovery_schemas import DiscoverySearchRequest

router = APIRouter(tags=["Discovery"])


@router.post("/discovery/search", response_model=CandidatePageView)
async def search_discovery(
    workspace_id: UUID,
    data: DiscoverySearchRequest,
    user: ApiUser,
    db: Database,
) -> CandidatePageView:
    return await search_candidate_records(
        db,
        user,
        workspace_id,
        data.provider,
        tuple(data.clauses),
        page=data.page,
        per_page=data.per_page,
        sort=data.sort,
        year_from=data.year_from,
        year_to=data.year_to,
        settings=await get_effective_settings_model(db),
    )


@router.get("/discovery/providers", response_model=MetadataProviderChoices)
async def discovery_providers(user: ApiUser, db: Database):
    del user
    return get_metadata_provider_choices(await get_effective_settings_model(db))
