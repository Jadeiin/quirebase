from __future__ import annotations

import json
from typing import TYPE_CHECKING

from inquiro.canonical import (
    clean_markup,
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import normalize_doi, parse_bibcode
from inquiro.models import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Contributor,
    Identifier,
    ProviderConfig,
    ProviderUnavailable,
    ResourceLink,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import (
    affiliation_values,
    boolean_query,
    keyword_values,
    text_contributors,
)
from inquiro.reference_types import ReferenceType, normalize_reference_type

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _contributors(document: dict) -> tuple[Contributor, ...] | None:
    names = document.get("author")
    affiliations = document.get("aff")
    if (
        isinstance(names, list)
        and isinstance(affiliations, list)
        and len(affiliations) == len(names)
    ):
        return tuple(
            Contributor(name, affiliations=affiliation_values([affiliation]))
            for raw_name, affiliation in zip(names, affiliations, strict=True)
            if (name := clean_markup(first_text(raw_name)))
        )
    return text_contributors(names)


def _record(doc: dict, identifier: Identifier) -> CandidateRecord:
    title = clean_rich_markup(first_text(doc.get("title")))
    if not title:
        raise CandidateNotFound("NASA ADS record was not found")
    doi = normalize_doi(first_text(doc.get("doi")) or "") or None
    bibcode = first_text(doc.get("bibcode")) or (
        identifier.value if identifier.provider == "bibcode" else None
    )
    identifiers = {"bibcode": bibcode}
    if doi:
        identifiers["doi"] = doi
    return CandidateRecord(
        provider="nasa_ads",
        lookup_identifier=identifier,
        title=title,
        abstract=clean_rich_markup(first_text(doc.get("abstract"))),
        authors=_contributors(doc),
        keywords=keyword_values(doc.get("keyword")),
        publication_date=first_text(doc.get("pubdate")),
        publication_title=first_text(doc.get("pub")),
        doi=doi,
        urls=(
            ResourceLink(
                f"https://ui.adsabs.harvard.edu/abs/{bibcode}/abstract", kind="landing_page"
            ),
        )
        if bibcode
        else None,
        identifiers=tuple(Identifier(key, value) for key, value in identifiers.items() if value),
        reference_type=normalize_reference_type(first_text(doc.get("doctype")), source="nasa_ads")
        or ReferenceType.article_journal,
    )


class NasaAdsLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        token = settings.nasa_ads_token or ""
        params = {
            "q": f'bibcode:"{value}"',
            "fl": "bibcode,title,author,aff,keyword,doi,pubdate,pub,abstract,doctype",
            "rows": "1",
        }
        headers = {"Authorization": f"Bearer {token}"}
        body = await client.get(endpoint, params, headers=headers)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("NASA ADS returned invalid metadata") from error
        docs = (payload.get("response") or {}).get("docs", [])
        if not docs:
            raise CandidateNotFound("NASA ADS record was not found")
        doc = docs[0]
        return _record(doc, identifier)


class NasaAdsSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        token = settings.nasa_ads_token or ""
        query = boolean_query(
            request.clauses,
            {
                "any": "",
                "title": "title:",
                "author": "author:",
                "publication": "bibstem:",
                "abstract": "abs:",
            },
            field_prefix=True,
        )
        if request.year_from or request.year_to:
            query += f" year:{request.year_from or 0}-{request.year_to or 3000}"
        sort_value = (
            "date desc"
            if request.sort == "published"
            else "citation_count desc"
            if request.sort == "cited"
            else "score desc"
        )
        params = {
            "q": query,
            "fl": "bibcode,title,author,aff,keyword,doi,pubdate,pub,abstract,doctype",
            "rows": str(request.per_page),
            "start": str((request.page - 1) * request.per_page),
            "sort": sort_value,
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            payload = json.loads(await client.get(endpoint, params, headers=headers))
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("NASA ADS returned invalid search results") from error
        response = payload.get("response", {})
        results = []
        for document in response.get("docs", []):
            title = first_text(document.get("title"))
            bibcode = first_text(document.get("bibcode"))
            doi = first_text(document.get("doi"))
            if not title or not (doi or bibcode):
                continue
            identifier = doi or bibcode
            assert identifier is not None
            results.append(
                _record(
                    document,
                    Identifier("doi", normalize_doi(doi))
                    if doi
                    else Identifier("bibcode", identifier),
                )
            )
        return CandidatePage(
            "nasa_ads",
            tuple(results),
            int(response.get("numFound", len(results))),
            request.page,
            request.per_page,
        )


NASA_ADS_PROVIDER = ProviderDefinition(
    name="nasa_ads",
    display_name="NASA ADS",
    identifier_namespace="bibcode",
    identifier_parser=parse_bibcode,
    search_adapter=NasaAdsSearchAdapter(),
    lookup_adapter=NasaAdsLookupAdapter(),
    endpoint="https://api.adsabs.harvard.edu/v1/search/query",
    credential_setting="nasa_ads_token",
    credential_environment="INQUIRO_NASA_ADS_TOKEN",
)
