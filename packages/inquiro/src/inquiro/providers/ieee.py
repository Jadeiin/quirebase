from __future__ import annotations

import json
from typing import Any

from inquiro.canonical import (
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import parse_article_number
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    PdfAccessDenied,
    PdfNotAvailable,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition

_IEEE_FIELDS = {
    "any": None,
    "title": '"Document Title"',
    "author": '"Author"',
    "publication": '"Publication Title"',
    "abstract": '"Abstract"',
}


def _ieee_boolean_query(clauses: list[SearchClause]) -> str:
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


class IeeeLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        api_key = getattr(settings, "ieee_api_key", None) or ""
        params = {
            "apikey": api_key,
            "format": "json",
            "article_number": value,
        }
        body = client._get(endpoint, params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("IEEE Xplore returned invalid metadata") from error
        articles = payload.get("articles", [])
        if not articles:
            raise CandidateNotFound("IEEE Xplore article was not found")
        article = articles[0]
        title = clean_rich_markup(first_text(article.get("title")))
        if not title:
            raise CandidateNotFound("IEEE Xplore article was not found")
        doi = first_text(article.get("doi"))
        article_number = first_text(article.get("article_number")) or value
        identifiers = {"article_number": article_number}
        if doi:
            identifiers["doi"] = doi
        authors = "; ".join(
            author.get("full_name", "")
            for author in (article.get("authors") or {}).get("authors", [])
            if author.get("full_name")
        )
        return ProviderRecord(
            title=title,
            abstract=clean_rich_markup(first_text(article.get("abstract"))),
            authors=authors or None,
            keywords=None,
            publication_date=first_text(article.get("publication_year")),
            publication_title=first_text(article.get("publication_title")),
            doi=doi,
            urls=f"https://ieeexplore.ieee.org/document/{value}",
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class IeeeSearchAdapter:
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
        api_key = getattr(settings, "ieee_api_key", None) or ""
        params = {
            "apikey": api_key,
            "format": "json",
            "querytext": _ieee_boolean_query(clauses),
            "startRecord": str((page - 1) * per_page + 1),
            "max_records": str(per_page),
        }
        if year_from:
            params["start_year"] = str(year_from)
        if year_to:
            params["end_year"] = str(year_to)
        if sort == "published":
            params["sort_field"] = "publication_year"
            params["sort_order"] = "desc"
        elif sort == "cited":
            params["sort_field"] = "article_citations"
            params["sort_order"] = "desc"
        try:
            payload = json.loads(client._get(endpoint, params))
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
                ProviderSearchRecord(
                    provider="ieee",
                    identifier_provider="doi" if doi else "article_number",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(
                        author.get("full_name", "")
                        for author in (article.get("authors") or {}).get("authors", [])
                        if author.get("full_name")
                    )
                    or None,
                    publication_title=first_text(article.get("publication_title")),
                    publication_date=first_text(article.get("publication_year")),
                    abstract=first_text(article.get("abstract")),
                )
            )
        return ProviderSearchPage(
            "ieee", results, int(payload.get("total_records", len(results))), page, per_page
        )


class IeeeDocumentAdapter:
    def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: Any,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        body = client._get(
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
        return client._download_pdf(
            pdf_url,
            filename=f"{value}.pdf",
            provider="ieee",
        )


IEEE_PROVIDER = ProviderDefinition(
    name="ieee",
    display_name="IEEE Xplore",
    identifier_aliases=("article_number",),
    identifier_parser=parse_article_number,
    search_adapter=IeeeSearchAdapter(),
    lookup_adapter=IeeeLookupAdapter(),
    document_adapter=IeeeDocumentAdapter(),
    endpoint="https://ieeexploreapi.ieee.org/api/v1/search/articles",
    credential_setting="ieee_api_key",
    credential_environment="INQUIRO_IEEE_API_KEY",
    credential_capabilities=frozenset({"lookup", "search", "document"}),
)
