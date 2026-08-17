from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quirebase.core.config import Settings
    from quirebase.discovery.lookup import Identifier

type IdentifierParser = Callable[[str, str], Identifier | None]


@dataclass(frozen=True)
class ProviderRegistration:
    name: str
    display_name: str | None = None
    identifier_aliases: tuple[str, ...] = ()
    identifier_parser: IdentifierParser | None = None
    auto_detect_identifier: bool = False
    search_adapter: object | None = None
    lookup_adapter: object | None = None
    endpoint: str = ""
    credential_setting: str | None = None
    credential_environment: str | None = None

    def require_credentials(self, settings: Settings) -> None:
        if self.credential_setting and not getattr(settings, self.credential_setting):
            from quirebase.discovery.lookup import MetadataLookupError

            raise MetadataLookupError(
                f"{self.display_name or self.name} requires "
                f"{self.credential_environment or self.credential_setting}"
            )


@cache
def provider_registrations() -> tuple[ProviderRegistration, ...]:
    from quirebase.discovery.lookup import (
        ArxivLookupAdapter,
        CrossrefLookupAdapter,
        DataCiteLookupAdapter,
        IeeeLookupAdapter,
        NasaAdsLookupAdapter,
        OpenAlexLookupAdapter,
        OpenLibraryLookupAdapter,
        PubMedLookupAdapter,
        _parse_arxiv_identifier,
        _parse_bibcode_identifier,
        _parse_doi_identifier,
        _parse_ieee_identifier,
        _parse_isbn_identifier,
        _parse_openalex_identifier,
        _parse_pmid_identifier,
    )
    from quirebase.discovery.search import (
        ArxivSearchAdapter,
        CrossrefSearchAdapter,
        IeeeSearchAdapter,
        NasaAdsSearchAdapter,
        OpenAlexSearchAdapter,
        OpenLibrarySearchAdapter,
        PmcSearchAdapter,
        PubMedSearchAdapter,
    )

    return (
        ProviderRegistration(
            name="crossref",
            identifier_aliases=("doi", "crossref"),
            identifier_parser=_parse_doi_identifier,
            auto_detect_identifier=True,
            search_adapter=CrossrefSearchAdapter(),
            lookup_adapter=CrossrefLookupAdapter(),
            endpoint="https://api.crossref.org/works",
        ),
        ProviderRegistration(
            name="datacite",
            identifier_aliases=("datacite",),
            identifier_parser=_parse_doi_identifier,
            lookup_adapter=DataCiteLookupAdapter(),
            endpoint="https://api.datacite.org/dois",
        ),
        ProviderRegistration(
            name="pubmed",
            identifier_aliases=("pmid", "pubmed"),
            identifier_parser=_parse_pmid_identifier,
            auto_detect_identifier=True,
            search_adapter=PubMedSearchAdapter(),
            lookup_adapter=PubMedLookupAdapter(),
            endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ),
        ProviderRegistration(
            name="pmc",
            search_adapter=PmcSearchAdapter(),
            endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
        ),
        ProviderRegistration(
            name="arxiv",
            identifier_aliases=("arxiv",),
            identifier_parser=_parse_arxiv_identifier,
            auto_detect_identifier=True,
            search_adapter=ArxivSearchAdapter(),
            lookup_adapter=ArxivLookupAdapter(),
            endpoint="https://export.arxiv.org/api/query",
        ),
        ProviderRegistration(
            name="openlibrary",
            identifier_aliases=("isbn",),
            identifier_parser=_parse_isbn_identifier,
            auto_detect_identifier=True,
            search_adapter=OpenLibrarySearchAdapter(),
            lookup_adapter=OpenLibraryLookupAdapter(),
            endpoint="https://openlibrary.org",
        ),
        ProviderRegistration(
            name="openalex",
            identifier_aliases=("openalex",),
            identifier_parser=_parse_openalex_identifier,
            auto_detect_identifier=True,
            search_adapter=OpenAlexSearchAdapter(),
            lookup_adapter=OpenAlexLookupAdapter(),
            endpoint="https://api.openalex.org",
        ),
        ProviderRegistration(
            name="nasa",
            display_name="NASA ADS",
            identifier_aliases=("bibcode",),
            identifier_parser=_parse_bibcode_identifier,
            search_adapter=NasaAdsSearchAdapter(),
            lookup_adapter=NasaAdsLookupAdapter(),
            endpoint="https://api.adsabs.harvard.edu/v1/search/query",
            credential_setting="nasa_ads_token",
            credential_environment="QUIREBASE_NASA_ADS_TOKEN",
        ),
        ProviderRegistration(
            name="ieee",
            display_name="IEEE Xplore",
            identifier_aliases=("article_number",),
            identifier_parser=_parse_ieee_identifier,
            search_adapter=IeeeSearchAdapter(),
            lookup_adapter=IeeeLookupAdapter(),
            endpoint="https://ieeexploreapi.ieee.org/api/v1/search/articles",
            credential_setting="ieee_api_key",
            credential_environment="QUIREBASE_IEEE_API_KEY",
        ),
    )


def search_provider(name: str) -> ProviderRegistration | None:
    return next(
        (registration for registration in provider_registrations() if registration.name == name),
        None,
    )


def identifier_provider(alias: str) -> ProviderRegistration | None:
    return next(
        (
            registration
            for registration in provider_registrations()
            if alias in registration.identifier_aliases
        ),
        None,
    )


def identifier_provider_names() -> tuple[str, ...]:
    return tuple(
        alias
        for registration in provider_registrations()
        for alias in registration.identifier_aliases
    )
