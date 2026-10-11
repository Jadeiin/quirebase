from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from inquiro.canonical import (
    first_text,
)
from inquiro.identifiers import normalize_doi, parse_arxiv
from inquiro.models import (
    AcquiredDocument,
    Affiliation,
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
    boolean_query,
    unique_links,
)
from inquiro.reference_types import ReferenceType

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport

_NAMESPACE = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _contributors(entry: ElementTree.Element) -> tuple[Contributor, ...]:
    authors = []
    for author in entry.findall("atom:author", _NAMESPACE):
        name = first_text(author.findtext("atom:name", namespaces=_NAMESPACE))
        if not name:
            continue
        affiliations = tuple(
            Affiliation(affiliation_name)
            for node in author.findall("arxiv:affiliation", _NAMESPACE)
            if (affiliation_name := first_text(node.text))
        )
        authors.append(Contributor(name, affiliations=affiliations or None))
    return tuple(authors)


def _links(entry: ElementTree.Element, value: str, doi: str | None) -> tuple[ResourceLink, ...]:
    links = []
    for node in entry.findall("atom:link", _NAMESPACE):
        if not (url := first_text(node.get("href"))):
            continue
        media_type = node.get("type")
        kind: Literal["full_text", "landing_page", "other"] = (
            "full_text"
            if node.get("title") == "pdf" or media_type == "application/pdf"
            else "landing_page"
            if node.get("rel") == "alternate" or node.get("title") == "doi"
            else "other"
        )
        links.append(ResourceLink(url, kind=kind, media_type=media_type))
    for link in (
        ResourceLink(f"https://arxiv.org/abs/{value}", kind="landing_page"),
        ResourceLink(
            f"https://arxiv.org/pdf/{value}.pdf", kind="full_text", media_type="application/pdf"
        ),
        ResourceLink(f"https://doi.org/{doi}", kind="landing_page") if doi else None,
    ):
        if link and not any(existing.url == link.url for existing in links):
            links.append(link)
    return unique_links(*links)


def _record(entry: ElementTree.Element, identifier: Identifier) -> CandidateRecord:
    value = identifier.value
    summary = entry.findtext("atom:summary", default="", namespaces=_NAMESPACE)
    if summary.strip().lower().startswith("error:"):
        raise CandidateNotFound("arXiv returned an error entry")
    doi = entry.findtext("arxiv:doi", default="", namespaces=_NAMESPACE) or None
    doi_link = entry.find("atom:link[@title='doi']", _NAMESPACE)
    if not doi and doi_link is not None:
        doi = normalize_doi(doi_link.attrib.get("href", "")) or None
    identifiers: dict[str, str] = {"arxiv": value}
    if doi:
        identifiers["doi"] = doi
    published = entry.findtext("atom:published", default="", namespaces=_NAMESPACE)
    return CandidateRecord(
        provider="arxiv",
        lookup_identifier=identifier,
        title=first_text(entry.findtext("atom:title", default="", namespaces=_NAMESPACE)) or "",
        abstract=summary.strip() or None,
        authors=_contributors(entry),
        keywords=tuple(
            dict.fromkeys(
                term
                for category in entry.findall("atom:category", _NAMESPACE)
                if (term := first_text(category.get("term")))
            )
        ),
        publication_date=published[:10] if published else None,
        publication_title=first_text(
            entry.findtext("arxiv:journal_ref", default="", namespaces=_NAMESPACE)
        ),
        doi=doi,
        urls=_links(entry, value, doi),
        identifiers=tuple(Identifier(key, value) for key, value in identifiers.items()),
        reference_type=ReferenceType.preprint,
    )


class ArxivLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        body = await client.get(
            endpoint,
            {"id_list": value, "max_results": "1"},
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("arXiv returned invalid XML") from error
        entry = root.find("atom:entry", _NAMESPACE)
        if entry is None or entry.find("atom:title", _NAMESPACE) is None:
            raise CandidateNotFound("arXiv entry was not found")
        return _record(entry, identifier)


class ArxivSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        query = boolean_query(
            request.clauses,
            {
                "any": "all:",
                "title": "ti:",
                "author": "au:",
                "publication": "jr:",
                "abstract": "abs:",
            },
            field_prefix=True,
        )
        if request.year_from or request.year_to:
            query += f" AND submittedDate:[{request.year_from or 1991}01010000 TO {request.year_to or 3000}12312359]"
        params = {
            "search_query": query,
            "start": str((request.page - 1) * request.per_page),
            "max_results": str(request.per_page),
            "sortBy": "submittedDate" if request.sort == "published" else "relevance",
            "sortOrder": "descending",
        }
        body = await client.get(endpoint, params)
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("arXiv returned invalid XML") from error
        total = int(
            root.findtext("opensearch:totalResults", default="0", namespaces=_NAMESPACE) or "0"
        )
        results = []
        for entry in root.findall("atom:entry", _NAMESPACE):
            title = first_text(entry.findtext("atom:title", default="", namespaces=_NAMESPACE))
            if not title:
                continue
            entry_id = entry.findtext("atom:id", default="", namespaces=_NAMESPACE)
            if identifier := parse_arxiv(entry_id, "arxiv"):
                record = _record(entry, identifier)
                results.append(
                    replace(record, publication_title=record.publication_title or "arXiv")
                )
        return CandidatePage("arxiv", tuple(results), total, request.page, request.per_page)


class ArxivDocumentAdapter:
    async def acquire(
        self,
        client: BoundedTransport,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        filename = f"{value.replace('/', '_')}.pdf"
        return await client.download_pdf(
            f"{endpoint}/{value}.pdf",
            filename=filename,
            provider="arxiv",
        )


ARXIV_PROVIDER = ProviderDefinition(
    name="arxiv",
    identifier_namespace="arxiv",
    identifier_parser=parse_arxiv,
    auto_detect_identifier=True,
    search_adapter=ArxivSearchAdapter(),
    lookup_adapter=ArxivLookupAdapter(),
    document_adapter=ArxivDocumentAdapter(),
    endpoint="https://export.arxiv.org/api/query",
    document_endpoint="https://arxiv.org/pdf",
)
