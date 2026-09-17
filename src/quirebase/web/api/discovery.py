from __future__ import annotations

from fastapi import APIRouter

from quirebase.library import CandidatePageView, search_candidate_records
from quirebase.operations.settings import get_effective_settings_model
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.discovery_schemas import DiscoveryProviderView, DiscoverySearchRequest

router = APIRouter(prefix="/api/v1", tags=["Discovery"])


@router.post("/discovery/search", response_model=CandidatePageView, operation_id="discovery.search")
async def search_discovery(
    data: DiscoverySearchRequest,
    user: ApiUser,
    db: Database,
) -> CandidatePageView:
    return await search_candidate_records(
        db,
        user,
        data.provider,
        tuple(data.clauses),
        page=data.page,
        per_page=data.per_page,
        sort=data.sort,
        year_from=data.year_from,
        year_to=data.year_to,
        settings=await get_effective_settings_model(db),
    )


@router.get("/discovery/providers", response_model=list[DiscoveryProviderView])
async def discovery_providers(user: ApiUser, db: Database):
    del user
    settings = await get_effective_settings_model(db)
    providers = [
        {"id": "openalex", "name": "OpenAlex"},
        {"id": "crossref", "name": "Crossref"},
        {"id": "pubmed", "name": "PubMed"},
        {"id": "arxiv", "name": "arXiv"},
        {"id": "openlibrary", "name": "Open Library"},
        {"id": "pmc", "name": "PMC"},
    ]
    if settings.nasa_ads_token:
        providers.append({"id": "nasa", "name": "NASA ADS"})
    if settings.ieee_api_key:
        providers.append({"id": "ieee", "name": "IEEE Xplore"})
    return providers
