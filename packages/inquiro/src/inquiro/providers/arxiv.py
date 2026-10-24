from __future__ import annotations

import re
from dataclasses import replace
from typing import TYPE_CHECKING, Literal
from xml.etree import ElementTree

from commonmeta.base_utils import compact

from inquiro.canonical import first_text
from inquiro.identifiers import normalize_doi, parse_arxiv
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Identifier,
    LookupFailure,
    ProviderConfig,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import (
    boolean_query,
    source_affiliation,
    source_credit,
    source_files,
    source_identifiers,
    source_landing_url,
    source_link,
    source_subjects,
    source_work_id,
    unique_links,
)

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport
_NAMESPACE = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _contributors(entry: ElementTree.Element) -> tuple[dict, ...] | None:
    authors = []
    for author in entry.findall("atom:author", _NAMESPACE):
        name = first_text(author.findtext("atom:name", namespaces=_NAMESPACE))
        if not name:
            continue
        affiliations = tuple(
            source_affiliation(affiliation_name)
            for node in author.findall("arxiv:affiliation", _NAMESPACE)
            if (affiliation_name := first_text(node.text))
        )
        authors.append(source_credit(name, affiliations=affiliations or None))
    return tuple(authors) or None


def _links(entry: ElementTree.Element, value: str, doi: str | None) -> tuple[dict, ...]:
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
        links.append(source_link(url, kind=kind, media_type=media_type))
    for link in (
        source_link(f"https://arxiv.org/abs/{value}", kind="landing_page"),
        source_link(
            f"https://arxiv.org/pdf/{value}.pdf", kind="full_text", media_type="application/pdf"
        ),
        source_link(f"https://doi.org/{doi}", kind="landing_page") if doi else None,
    ):
        if link and (not any(existing["url"] == link["url"] for existing in links)):
            links.append(link)
    return unique_links(*links)


def _record(entry: ElementTree.Element, identifier: Identifier) -> CandidateRecord:
    returned = entry.findtext("atom:id", default="", namespaces=_NAMESPACE)
    confirmed = parse_arxiv(returned, "arxiv")
    value = confirmed.value if confirmed else ""
    summary = entry.findtext("atom:summary", default="", namespaces=_NAMESPACE)
    if summary.strip().lower().startswith("error:"):
        raise CandidateNotFound("arXiv returned an error entry")
    doi = entry.findtext("arxiv:doi", default="", namespaces=_NAMESPACE) or None
    doi_link = entry.find("atom:link[@title='doi']", _NAMESPACE)
    if not doi and doi_link is not None:
        doi = normalize_doi(doi_link.attrib.get("href", "")) or None
    identifiers: dict[str, str] = {"arxiv": value} if value else {}
    if doi:
        identifiers["doi"] = doi
    published = entry.findtext("atom:published", default="", namespaces=_NAMESPACE)
    return CandidateRecord(
        provider="arxiv",
        lookup_identifier=identifier,
        work=compact({
            "id": source_work_id(
                tuple((Identifier(key, value) for key, value in identifiers.items()))
            ),
            "type": "Preprint",
            "title": first_text(entry.findtext("atom:title", default="", namespaces=_NAMESPACE))
            or "",
            "description": summary.strip() or None,
            "contributors": _contributors(entry),
            "date_published": published[:10] if published else None,
            "identifiers": source_identifiers(
                tuple((Identifier(key, value) for key, value in identifiers.items()))
            ),
            "subjects": source_subjects(
                tuple(
                    dict.fromkeys(
                        term
                        for category in entry.findall("atom:category", _NAMESPACE)
                        if (term := first_text(category.get("term")))
                    )
                )
                or ()
            ),
            "container": compact({
                "title": first_text(
                    entry.findtext("arxiv:journal_ref", default="", namespaces=_NAMESPACE)
                )
            }),
            "url": source_landing_url(_links(entry, value, doi)),
            "files": source_files(_links(entry, value, doi)),
        }),
    )


class ArxivLookupAdapter:
    async def lookup_many(
        self,
        client: BoundedTransport,
        identifiers: tuple[Identifier, ...],
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> tuple[CandidateRecord | LookupFailure, ...]:
        values = tuple(dict.fromkeys(identifier.value for identifier in identifiers))
        body = await client.get(
            endpoint, {"id_list": ",".join(values), "max_results": str(len(values))}
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("arXiv returned invalid XML") from error
        if root.tag != f"{{{_NAMESPACE['atom']}}}feed":
            raise ProviderUnavailable("arXiv returned an invalid feed")
        entries = root.findall("atom:entry", _NAMESPACE)
        total = root.findtext("opensearch:totalResults", namespaces=_NAMESPACE)
        if total is not None and int(total) > len(entries):
            raise ProviderUnavailable("arXiv returned an incomplete feed")
        versions: dict[str, list[ElementTree.Element]] = {}
        latest: dict[str, tuple[int, str]] = {}
        unassociated = False
        for entry in entries:
            entry_id = entry.findtext("atom:id", default="", namespaces=_NAMESPACE)
            confirmed = parse_arxiv(entry_id, "arxiv")
            if confirmed is None:
                unassociated = True
                continue
            key = confirmed.value.casefold()
            versions.setdefault(key, []).append(entry)
            base = re.sub(r"v\d+$", "", key)
            version = int(key[len(base) + 1 :]) if base != key else 0
            if base not in latest or version > latest[base][0]:
                latest[base] = (version, key)
        results: list[CandidateRecord | LookupFailure] = []
        for identifier in identifiers:
            key = identifier.value.casefold()
            if not re.search(r"v\d+$", key) and key in latest:
                key = latest[key][1]
            matches = versions.get(key, [])
            if len(matches) != 1:
                if matches or unassociated:
                    results.append(
                        LookupFailure(
                            "unavailable", "arXiv returned ambiguous or incomplete metadata"
                        )
                    )
                else:
                    results.append(LookupFailure("not_found", "arXiv entry was not found"))
                continue
            entry = matches[0]
            if entry.find("atom:title", _NAMESPACE) is None:
                results.append(
                    LookupFailure("unavailable", "arXiv returned an entry without a title")
                )
                continue
            try:
                results.append(_record(entry, identifier))
            except CandidateNotFound as error:
                results.append(LookupFailure("not_found", str(error)))
            except (TypeError, ValueError, ProviderUnavailable):
                results.append(LookupFailure("unavailable", "arXiv returned invalid metadata"))
        return tuple(results)


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
                container = {"title": "arXiv", **record.work.get("container", {})}
                results.append(replace(record, work={**record.work, "container": container}))
        return CandidatePage("arxiv", tuple(results), total, request.page, request.per_page)


class ArxivDocumentAdapter:
    async def acquire(
        self, client: BoundedTransport, value: str, settings: ProviderConfig, *, endpoint: str
    ) -> AcquiredDocument:
        filename = f"{value.replace('/', '_')}.pdf"
        return await client.download_pdf(
            f"{endpoint}/{value}.pdf", filename=filename, provider="arxiv"
        )


ARXIV_PROVIDER = ProviderDefinition(
    name="arxiv",
    display_name="arXiv",
    identifier_namespace="arxiv",
    identifier_parser=parse_arxiv,
    auto_detect_identifier=True,
    search_adapter=ArxivSearchAdapter(),
    batch_lookup_adapter=ArxivLookupAdapter(),
    document_adapter=ArxivDocumentAdapter(),
    endpoint="https://export.arxiv.org/api/query",
    document_endpoint="https://arxiv.org/pdf",
)
