from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from inquiro.providers._contracts import ProviderDefinition


@cache
def builtin_providers() -> tuple[ProviderDefinition, ...]:
    from inquiro.providers.arxiv import ARXIV_PROVIDER
    from inquiro.providers.crossref import CROSSREF_PROVIDER
    from inquiro.providers.datacite import DATACITE_PROVIDER
    from inquiro.providers.ieee import IEEE_PROVIDER
    from inquiro.providers.nasa_ads import NASA_ADS_PROVIDER
    from inquiro.providers.openalex import OPENALEX_PROVIDER
    from inquiro.providers.openlibrary import OPENLIBRARY_PROVIDER
    from inquiro.providers.pmc import PMC_PROVIDER
    from inquiro.providers.pubmed import PUBMED_PROVIDER

    return (
        CROSSREF_PROVIDER,
        DATACITE_PROVIDER,
        PUBMED_PROVIDER,
        PMC_PROVIDER,
        ARXIV_PROVIDER,
        OPENLIBRARY_PROVIDER,
        OPENALEX_PROVIDER,
        NASA_ADS_PROVIDER,
        IEEE_PROVIDER,
    )
