from __future__ import annotations

import json
from typing import Any

from inquiro.identifiers import parse_bibcode
from inquiro.models import (
    CandidateNotFound,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.parsing import (
    _boolean_query,
    _clean_markup,
    _first,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


class NasaAdsLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        token = getattr(settings, "nasa_ads_token", None) or ""
        params = {
            "q": f'bibcode:"{value}"',
            "fl": "bibcode,title,author,doi,pubdate,pub,abstract",
            "rows": "1",
        }
        headers = {"Authorization": f"Bearer {token}"}
        body = client._get(endpoint, params, headers=headers)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("NASA ADS returned invalid metadata") from error
        docs = (payload.get("response") or {}).get("docs", [])
        if not docs:
            raise CandidateNotFound("NASA ADS record was not found")
        doc = docs[0]
        title = _clean_markup(_first(doc.get("title")))
        if not title:
            raise CandidateNotFound("NASA ADS record was not found")
        doi = _first(doc.get("doi"))
        bibcode = _first(doc.get("bibcode")) or value
        identifiers = {"bibcode": bibcode}
        if doi:
            identifiers["doi"] = doi
        return ProviderRecord(
            title=title,
            abstract=_clean_markup(_first(doc.get("abstract"))),
            authors="; ".join(doc.get("author", [])) or None,
            keywords=None,
            publication_date=_first(doc.get("pubdate")),
            publication_title=_first(doc.get("pub")),
            doi=doi,
            urls=f"https://ui.adsabs.harvard.edu/abs/{value}/abstract",
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class NasaAdsSearchAdapter:
    def search(
        self,
        client: ProviderContext,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Any,
        endpoint: str,
    ) -> ProviderSearchPage:
        token = getattr(settings, "nasa_ads_token", None) or ""
        query = _boolean_query(
            clauses,
            {
                "any": "",
                "title": "title:",
                "author": "author:",
                "publication": "bibstem:",
                "abstract": "abs:",
            },
            field_prefix=True,
        )
        if year_from or year_to:
            query += f" year:{year_from or 0}-{year_to or 3000}"
        sort_value = (
            "date desc"
            if sort == "published"
            else "citation_count desc"
            if sort == "cited"
            else "score desc"
        )
        params = {
            "q": query,
            "fl": "bibcode,title,author,doi,pubdate,pub,abstract",
            "rows": str(per_page),
            "start": str((page - 1) * per_page),
            "sort": sort_value,
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            payload = json.loads(client._get(endpoint, params, headers=headers))
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("NASA ADS returned invalid search results") from error
        response = payload.get("response", {})
        results = []
        for document in response.get("docs", []):
            title = _first(document.get("title"))
            bibcode = _first(document.get("bibcode"))
            doi = _first(document.get("doi"))
            if not title or not (doi or bibcode):
                continue
            identifier = doi or bibcode
            assert identifier is not None
            results.append(
                ProviderSearchRecord(
                    provider="nasa",
                    identifier_provider="doi" if doi else "bibcode",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(document.get("author", [])) or None,
                    publication_title=_first(document.get("pub")),
                    publication_date=_first(document.get("pubdate")),
                    abstract=_first(document.get("abstract")),
                )
            )
        return ProviderSearchPage(
            "nasa", results, int(response.get("numFound", len(results))), page, per_page
        )


NASA_ADS_PROVIDER = ProviderDefinition(
    name="nasa",
    display_name="NASA ADS",
    identifier_aliases=("bibcode",),
    identifier_parser=parse_bibcode,
    search_adapter=NasaAdsSearchAdapter(),
    lookup_adapter=NasaAdsLookupAdapter(),
    endpoint="https://api.adsabs.harvard.edu/v1/search/query",
    credential_setting="nasa_ads_token",
    credential_environment="QUIREBASE_NASA_ADS_TOKEN",
)
