from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from inquiro.canonical import (
    clean_markup,
    clean_rich_markup,
    collect_urls,
    first_text,
    normalize_reference_type,
)
from inquiro.identifiers import parse_doi
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    PdfNotAvailable,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition
from inquiro.providers._payload import (
    date_parts,
)


class CrossrefLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        contact = settings.contact_email
        params = {"mailto": contact} if contact else None
        body = client._get(f"{endpoint}/{quote(value, safe='')}", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Crossref returned invalid metadata") from error
        message = payload.get("message")
        if not message:
            raise CandidateNotFound("Crossref message was missing")
        authors = "; ".join(
            ", ".join(
                part
                for part in (
                    clean_markup(first_text(author.get("family"))),
                    clean_markup(first_text(author.get("given"))),
                )
                if part
            )
            for author in message.get("author", [])
            if isinstance(author, dict)
        )
        canonical_doi = first_text(message.get("DOI")) or value

        affiliations: list[str] = []
        for author in message.get("author", []):
            if not isinstance(author, dict):
                continue
            for affiliation in author.get("affiliation", []):
                if not isinstance(affiliation, dict):
                    continue
                name = clean_markup(first_text(affiliation.get("name")))
                if name and name not in affiliations:
                    affiliations.append(name)

        resource = message.get("resource") or {}
        primary_resource = resource.get("primary") or {}
        urls = collect_urls(
            f"https://doi.org/{canonical_doi}",
            first_text(message.get("URL")),
            first_text(primary_resource.get("URL")),
            *(
                first_text(link.get("URL"))
                for link in message.get("link", [])
                if isinstance(link, dict)
            ),
        )
        keywords = "; ".join(
            keyword
            for subject in message.get("subject", [])
            if (keyword := clean_markup(first_text(subject)))
        )
        return ProviderRecord(
            title=clean_rich_markup(first_text(message.get("title"))) or "",
            abstract=clean_rich_markup(first_text(message.get("abstract"))),
            authors=authors or None,
            keywords=keywords or None,
            publication_date=date_parts(message),
            publication_title=clean_markup(first_text(message.get("container-title"))),
            journal_abbreviation=clean_markup(first_text(message.get("short-container-title"))),
            volume=clean_markup(first_text(message.get("volume"))),
            issue=clean_markup(
                first_text(message.get("issue") or (message.get("journal-issue") or {}).get("issue"))
            ),
            pages=clean_markup(first_text(message.get("page"))),
            publisher=clean_markup(first_text(message.get("publisher"))),
            affiliation="; ".join(affiliations) or None,
            doi=canonical_doi,
            urls=urls,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(message.get("type")),
        )


class CrossrefSearchAdapter:
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
        params: dict[str, Any] = {
            "rows": str(per_page),
            "offset": str((page - 1) * per_page),
            "sort": {
                "published": "published",
                "updated": "updated",
                "cited": "is-referenced-by-count",
            }.get(sort, "score"),
            "order": "desc",
        }
        contact = settings.contact_email
        if contact:
            params["mailto"] = contact
        field_names = {
            "any": "query.bibliographic",
            "title": "query.title",
            "author": "query.author",
            "publication": "query.container-title",
            "abstract": "query.bibliographic",
        }
        if all(clause.operator == "and" for clause in clauses):
            for clause in clauses:
                key = field_names[clause.field]
                params[key] = " ".join(filter(None, [params.get(key), clause.term.strip()]))
        else:
            expressions: list[str] = []
            for index, clause in enumerate(clauses):
                term = clause.term.replace('"', " ").strip()
                operator = (
                    "NOT"
                    if clause.operator == "not"
                    else "OR"
                    if clause.operator == "or"
                    else "AND"
                )
                prefix = f"{operator} " if index or operator == "NOT" else ""
                expressions.append(f'{prefix}"{term}"')
            params["query.bibliographic"] = " ".join(expressions)
        filters = []
        if year_from:
            filters.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filters.append(f"until-pub-date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        body = client._get(endpoint, params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Crossref returned invalid metadata") from error
        message = payload.get("message", {})
        total = int(message.get("total-results", 0))
        results: list[ProviderSearchRecord] = []
        for item in message.get("items", []):
            doi = first_text(item.get("DOI"))
            if not doi:
                continue
            authors = "; ".join(
                ", ".join(
                    part
                    for part in (
                        clean_markup(first_text(author.get("family"))),
                        clean_markup(first_text(author.get("given"))),
                    )
                    if part
                )
                for author in item.get("author", [])
                if isinstance(author, dict)
            )
            results.append(
                ProviderSearchRecord(
                    provider="crossref",
                    identifier_provider="doi",
                    identifier=doi,
                    title=clean_rich_markup(first_text(item.get("title"))) or "",
                    authors=authors or None,
                    publication_title=clean_markup(first_text(item.get("container-title"))),
                    publication_date=date_parts(item),
                    doi=doi,
                    abstract=clean_rich_markup(first_text(item.get("abstract"))),
                )
            )
        return ProviderSearchPage("crossref", results, total, page, per_page)


class CrossrefDocumentAdapter:
    def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: Any,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        params = {"mailto": settings.contact_email} if settings.contact_email else None
        body = client._get(f"{endpoint}/{quote(value, safe='')}", params)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise TypeError
            message = payload.get("message") or {}
            if not isinstance(message, dict):
                raise TypeError
            links = message.get("link", [])
            if not isinstance(links, list):
                raise TypeError
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Crossref returned invalid document metadata") from error
        pdf_url = next(
            (
                first_text(link.get("URL"))
                for link in links
                if isinstance(link, dict)
                and (
                    first_text(link.get("content-type")) == "application/pdf"
                    or ".pdf" in (first_text(link.get("URL")) or "").lower()
                )
                and first_text(link.get("URL"))
            ),
            None,
        )
        if not pdf_url:
            raise PdfNotAvailable("Crossref does not provide a PDF link for this DOI")
        return client._download_pdf(pdf_url, provider="crossref")


CROSSREF_PROVIDER = ProviderDefinition(
    name="crossref",
    identifier_aliases=("doi", "crossref"),
    identifier_parser=parse_doi,
    auto_detect_identifier=True,
    search_adapter=CrossrefSearchAdapter(),
    lookup_adapter=CrossrefLookupAdapter(),
    document_adapter=CrossrefDocumentAdapter(),
    endpoint="https://api.crossref.org/works",
)
