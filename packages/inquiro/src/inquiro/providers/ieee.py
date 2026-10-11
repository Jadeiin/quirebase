from __future__ import annotations

import json
from typing import TYPE_CHECKING, Literal

from inquiro.canonical import (
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import normalize_doi, parse_ieee
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Contributor,
    Identifier,
    PdfAccessDenied,
    PdfNotAvailable,
    ProviderConfig,
    ProviderUnavailable,
    ResourceLink,
    SearchClause,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import affiliation_values, keyword_values, unique_links
from inquiro.reference_types import ReferenceType, normalize_reference_type

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.transport import BoundedTransport

_IEEE_FIELDS = {
    "any": None,
    "title": '"Document Title"',
    "author": '"Author"',
    "publication": '"Publication Title"',
    "abstract": '"Abstract"',
}


def _ieee_boolean_query(clauses: Sequence[SearchClause]) -> str:
    parts = []
    for index, clause in enumerate(clauses):
        value = clause.term.replace('"', " ").replace("\\", " ").strip()
        field = _IEEE_FIELDS[clause.field]
        tagged = f"{field}:{value}" if field else value
        if clause.operator == "not":
            parts.append(f"NOT {tagged}")
        elif index and clause.operator == "or":
            parts.append(f"OR {tagged}")
        else:
            parts.append(("AND " if index else "") + tagged)
    return " ".join(parts)


def _contributors(article: dict) -> tuple[Contributor, ...] | None:
    entries = (article.get("authors") or {}).get("authors")
    if not isinstance(entries, list):
        return None
    authors = []
    for author in entries:
        if not (name := first_text(author.get("full_name"))):
            continue
        affiliation = author.get("affiliation")
        if isinstance(affiliation, (str, dict)):
            affiliation = [affiliation]
        orcid = first_text(author.get("orcid"))
        authors.append(
            Contributor(
                display_name=name,
                family_name=first_text(author.get("last_name")),
                given_name=first_text(author.get("first_name")),
                identifiers=(Identifier("orcid", orcid),) if orcid else (),
                affiliations=affiliation_values(affiliation),
            )
        )
    return tuple(authors)


def _links(article: dict, article_number: str) -> tuple[ResourceLink, ...]:
    links = [
        ResourceLink(f"https://ieeexplore.ieee.org/document/{article_number}", kind="landing_page")
    ]
    fields: tuple[tuple[str, Literal["landing_page", "full_text"], str | None], ...] = (
        ("abstract_url", "landing_page", None),
        ("html_url", "full_text", "text/html"),
        ("pdf_url", "full_text", "application/pdf"),
    )
    for key, kind, media_type in fields:
        if url := first_text(article.get(key)):
            links.append(ResourceLink(url, kind=kind, media_type=media_type))
    return unique_links(*links)


def _keywords(article: dict) -> tuple[str, ...] | None:
    terms = article.get("index_terms")
    if not isinstance(terms, dict):
        return None
    return keyword_values([
        term
        for collection in terms.values()
        if isinstance(collection, dict)
        for term in collection.get("terms", [])
    ])


def _record(article: dict, identifier: Identifier) -> CandidateRecord:
    title = clean_rich_markup(first_text(article.get("title")))
    if not title:
        raise CandidateNotFound("IEEE Xplore article was not found")
    doi = normalize_doi(first_text(article.get("doi")) or "") or None
    article_number = first_text(article.get("article_number")) or (
        identifier.value if identifier.provider == "ieee" else None
    )
    identifiers = {"ieee": article_number}
    if doi:
        identifiers["doi"] = doi
    return CandidateRecord(
        provider="ieee",
        lookup_identifier=identifier,
        title=title,
        abstract=clean_rich_markup(first_text(article.get("abstract"))),
        authors=_contributors(article),
        keywords=_keywords(article),
        publication_date=first_text(article.get("publication_year")),
        publication_title=first_text(article.get("publication_title")),
        urls=_links(article, article_number) if article_number else None,
        identifiers=tuple(Identifier(key, value) for key, value in identifiers.items() if value),
        reference_type=normalize_reference_type(
            first_text(article.get("content_type")), source="ieee"
        )
        or ReferenceType.article_journal,
    )


class IeeeLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        api_key = settings.ieee_api_key or ""
        params = {
            "apikey": api_key,
            "format": "json",
            "article_number": value,
        }
        body = await client.get(endpoint, params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("IEEE Xplore returned invalid metadata") from error
        articles = payload.get("articles", [])
        if not articles:
            raise CandidateNotFound("IEEE Xplore article was not found")
        article = articles[0]
        return _record(article, identifier)


class IeeeSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        api_key = settings.ieee_api_key or ""
        params = {
            "apikey": api_key,
            "format": "json",
            "querytext": _ieee_boolean_query(request.clauses),
            "startRecord": str((request.page - 1) * request.per_page + 1),
            "max_records": str(request.per_page),
        }
        if request.year_from:
            params["start_year"] = str(request.year_from)
        if request.year_to:
            params["end_year"] = str(request.year_to)
        if request.sort == "published":
            params["sort_field"] = "publication_year"
            params["sort_order"] = "desc"
        elif request.sort == "cited":
            params["sort_field"] = "article_citations"
            params["sort_order"] = "desc"
        try:
            payload = json.loads(await client.get(endpoint, params))
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("IEEE Xplore returned invalid search results") from error
        results = []
        for article in payload.get("articles", []):
            title = first_text(article.get("title"))
            if not title:
                continue
            doi = first_text(article.get("doi"))
            article_number = first_text(article.get("article_number"))
            identifier = doi or article_number
            if identifier is None:
                continue
            results.append(
                _record(
                    article,
                    Identifier("doi", normalize_doi(doi))
                    if doi
                    else Identifier("ieee", identifier),
                )
            )
        return CandidatePage(
            "ieee",
            tuple(results),
            int(payload.get("total_records", len(results))),
            request.page,
            request.per_page,
        )


class IeeeDocumentAdapter:
    async def acquire(
        self,
        client: BoundedTransport,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        body = await client.get(
            endpoint,
            {
                "apikey": settings.ieee_api_key,
                "format": "json",
                "article_number": value,
            },
        )
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise TypeError
            articles = payload.get("articles", [])
            if not isinstance(articles, list):
                raise TypeError
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("IEEE Xplore returned invalid document metadata") from error
        if not articles:
            raise PdfNotAvailable("IEEE Xplore article was not found")
        article = articles[0]
        if not isinstance(article, dict):
            raise ProviderUnavailable("IEEE Xplore returned invalid document metadata")
        access_type = (first_text(article.get("accessType")) or "").lower()
        if access_type not in {"open access", "ephemera"}:
            raise PdfAccessDenied("IEEE Xplore PDF is not openly accessible")
        # IEEE's /fulltext API returns structured article text; pdf_url is the PDF resource.
        pdf_url = first_text(article.get("pdf_url"))
        if not pdf_url:
            raise PdfNotAvailable("IEEE Xplore did not provide a PDF link")
        return await client.download_pdf(
            pdf_url,
            filename=f"{value}.pdf",
            provider="ieee",
        )


IEEE_PROVIDER = ProviderDefinition(
    name="ieee",
    display_name="IEEE Xplore",
    identifier_namespace="ieee",
    identifier_parser=parse_ieee,
    search_adapter=IeeeSearchAdapter(),
    search_sorts=("relevance", "published", "cited"),
    lookup_adapter=IeeeLookupAdapter(),
    document_adapter=IeeeDocumentAdapter(),
    endpoint="https://ieeexploreapi.ieee.org/api/v1/search/articles",
    credential_setting="ieee_api_key",
    credential_environment="INQUIRO_IEEE_API_KEY",
    credential_capabilities=frozenset({"lookup", "search", "document"}),
)
