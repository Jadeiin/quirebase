from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from inquiro.canonical import (
    clean_markup,
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import normalize_doi, parse_doi
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Contributor,
    Identifier,
    PdfNotAvailable,
    ProviderConfig,
    ProviderUnavailable,
    ResourceLink,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import (
    affiliation_values,
    date_parts,
    keyword_values,
    unique_links,
)
from inquiro.reference_types import normalize_reference_type

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _contributors(message: dict) -> tuple[Contributor, ...] | None:
    entries = message.get("author")
    if not isinstance(entries, list):
        return None
    contributors = []
    for author in entries:
        if not isinstance(author, dict):
            continue
        family = clean_markup(first_text(author.get("family")))
        given = clean_markup(first_text(author.get("given")))
        display = clean_markup(first_text(author.get("name"))) or ", ".join(
            part for part in (family, given) if part
        )
        if not display:
            continue
        orcid = first_text(author.get("ORCID"))
        contributors.append(
            Contributor(
                display_name=display,
                family_name=family,
                given_name=given,
                kind="person" if family or given else "unknown",
                identifiers=(Identifier("orcid", orcid),) if orcid else (),
                affiliations=affiliation_values(author.get("affiliation")),
            )
        )
    return tuple(contributors)


def _links(message: dict, doi: str) -> tuple[ResourceLink, ...]:
    links = [ResourceLink(f"https://doi.org/{doi}", kind="landing_page")]
    resource = (message.get("resource") or {}).get("primary") or {}
    links.extend(
        ResourceLink(url, kind="landing_page")
        for value in (message.get("URL"), resource.get("URL"))
        if (url := first_text(value))
    )
    links.extend(
        ResourceLink(
            url,
            kind="full_text",
            media_type=first_text(entry.get("content-type")),
            version=first_text(entry.get("content-version")),
            intended_application=first_text(entry.get("intended-application")),
        )
        for entry in message.get("link", [])
        if isinstance(entry, dict) and (url := first_text(entry.get("URL")))
    )
    return unique_links(*links)


def _record(message: dict, identifier: Identifier) -> CandidateRecord:
    value = identifier.value
    canonical_doi = normalize_doi(first_text(message.get("DOI")) or value)
    return CandidateRecord(
        provider="crossref",
        lookup_identifier=identifier,
        title=clean_rich_markup(first_text(message.get("title"))) or "",
        abstract=clean_rich_markup(first_text(message.get("abstract"))),
        authors=_contributors(message),
        keywords=keyword_values(message.get("subject")),
        publication_date=date_parts(message),
        publication_title=clean_markup(first_text(message.get("container-title"))),
        journal_abbreviation=clean_markup(first_text(message.get("short-container-title"))),
        volume=clean_markup(first_text(message.get("volume"))),
        issue=clean_markup(
            first_text(message.get("issue") or (message.get("journal-issue") or {}).get("issue"))
        ),
        pages=clean_markup(first_text(message.get("page"))),
        publisher=clean_markup(first_text(message.get("publisher"))),
        urls=_links(message, canonical_doi),
        identifiers=(Identifier("doi", canonical_doi),),
        reference_type=normalize_reference_type(message.get("type"), source="crossref"),
    )


class CrossrefLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        contact = settings.contact_email
        params = {"mailto": contact} if contact else None
        body = await client.get(f"{endpoint}/{quote(value, safe='')}", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Crossref returned invalid metadata") from error
        message = payload.get("message")
        if not message:
            raise CandidateNotFound("Crossref message was missing")
        return _record(message, identifier)


class CrossrefSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        params: dict[str, Any] = {
            "rows": str(request.per_page),
            "offset": str((request.page - 1) * request.per_page),
            "sort": {
                "published": "published",
                "updated": "updated",
                "cited": "is-referenced-by-count",
            }.get(request.sort, "score"),
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
        if all(clause.operator == "and" for clause in request.clauses):
            for clause in request.clauses:
                key = field_names[clause.field]
                params[key] = " ".join(filter(None, [params.get(key), clause.term.strip()]))
        else:
            expressions: list[str] = []
            for index, clause in enumerate(request.clauses):
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
        if request.year_from:
            filters.append(f"from-pub-date:{request.year_from}-01-01")
        if request.year_to:
            filters.append(f"until-pub-date:{request.year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        body = await client.get(endpoint, params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Crossref returned invalid metadata") from error
        message = payload.get("message", {})
        total = int(message.get("total-results", 0))
        results: list[CandidateRecord] = []
        for item in message.get("items", []):
            doi = first_text(item.get("DOI"))
            if not doi:
                continue
            results.append(_record(item, Identifier("doi", normalize_doi(doi))))
        return CandidatePage("crossref", tuple(results), total, request.page, request.per_page)


class CrossrefDocumentAdapter:
    async def acquire(
        self,
        client: BoundedTransport,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        params = {"mailto": settings.contact_email} if settings.contact_email else None
        body = await client.get(f"{endpoint}/{quote(value, safe='')}", params)
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
        return await client.download_pdf(pdf_url, provider="crossref")


CROSSREF_PROVIDER = ProviderDefinition(
    name="crossref",
    display_name="Crossref",
    identifier_namespace="doi",
    identifier_parser=parse_doi,
    auto_detect_identifier=True,
    search_adapter=CrossrefSearchAdapter(),
    search_sorts=("relevance", "published", "cited", "updated"),
    lookup_adapter=CrossrefLookupAdapter(),
    document_adapter=CrossrefDocumentAdapter(),
    endpoint="https://api.crossref.org/works",
)
