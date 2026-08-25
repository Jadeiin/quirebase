from __future__ import annotations

import json
import re
from typing import Any
from xml.etree import ElementTree

from inquiro.identifiers import normalize_doi, parse_arxiv
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.parsing import (
    _boolean_query,
    _collect_urls,
    _first,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


class ArxivLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        body = client._get(
            endpoint,
            {"id_list": value, "max_results": "1"},
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("arXiv returned invalid XML") from error
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        entry = root.find("atom:entry", namespace)
        if entry is None or entry.find("atom:title", namespace) is None:
            raise CandidateNotFound("arXiv entry was not found")
        summary = entry.findtext("atom:summary", default="", namespaces=namespace)
        if summary.strip().lower().startswith("error:"):
            raise CandidateNotFound("arXiv returned an error entry")
        doi = entry.findtext("arxiv:doi", default="", namespaces=namespace) or None
        doi_link = entry.find("atom:link[@title='doi']", namespace)
        if not doi and doi_link is not None:
            doi = normalize_doi(doi_link.attrib.get("href", "")) or None
        identifiers: dict[str, str] = {"arxiv": value}
        urls = _collect_urls(
            f"https://arxiv.org/abs/{value}",
            f"https://arxiv.org/pdf/{value}.pdf",
            f"https://doi.org/{doi}" if doi else None,
        )
        if doi:
            identifiers["doi"] = doi
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        return ProviderRecord(
            title=_first(entry.findtext("atom:title", default="", namespaces=namespace)) or "",
            abstract=summary.strip() or None,
            authors="; ".join(
                author.findtext("atom:name", default="", namespaces=namespace).strip()
                for author in entry.findall("atom:author", namespace)
                if author.findtext("atom:name", default="", namespaces=namespace).strip()
            )
            or None,
            keywords="; ".join(
                category.attrib.get("term", "").strip()
                for category in entry.findall("atom:category", namespace)
                if category.attrib.get("term", "").strip()
            )
            or None,
            publication_date=published[:10] if published else None,
            publication_title=_first(
                entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)
            ),
            doi=doi,
            urls=urls,
            identifiers=json.dumps(identifiers),
            reference_type="preprint",
        )


class ArxivSearchAdapter:
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
        query = _boolean_query(
            clauses,
            {
                "any": "all:",
                "title": "ti:",
                "author": "au:",
                "publication": "jr:",
                "abstract": "abs:",
            },
            field_prefix=True,
        )
        if year_from or year_to:
            query += (
                f" AND submittedDate:[{year_from or 1991}01010000 TO {year_to or 3000}12312359]"
            )
        params = {
            "search_query": query,
            "start": str((page - 1) * per_page),
            "max_results": str(per_page),
            "sortBy": "submittedDate" if sort == "published" else "relevance",
            "sortOrder": "descending",
        }
        body = client._get(endpoint, params)
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("arXiv returned invalid XML") from error
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
        }
        total = int(
            root.findtext("opensearch:totalResults", default="0", namespaces=namespace) or "0"
        )
        results = []
        for entry in root.findall("atom:entry", namespace):
            title = _first(entry.findtext("atom:title", default="", namespaces=namespace))
            if not title:
                continue
            entry_id = entry.findtext("atom:id", default="", namespaces=namespace)
            arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", entry_id).removesuffix(".pdf")
            published = entry.findtext("atom:published", default="", namespaces=namespace)
            authors = "; ".join(
                author.findtext("atom:name", default="", namespaces=namespace).strip()
                for author in entry.findall("atom:author", namespace)
                if author.findtext("atom:name", default="", namespaces=namespace).strip()
            )
            results.append(
                ProviderSearchRecord(
                    provider="arxiv",
                    identifier_provider="arxiv",
                    identifier=arxiv_id,
                    title=title,
                    authors=authors or None,
                    publication_title=entry.findtext(
                        "arxiv:journal_ref",
                        default=None,
                        namespaces={"arxiv": "http://arxiv.org/schemas/atom"},
                    )
                    or "arXiv",
                    publication_date=published[:10] if published else None,
                )
            )
        return ProviderSearchPage("arxiv", results, total, page, per_page)


class ArxivDocumentAdapter:
    def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: Any,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        filename = f"{value.replace('/', '_')}.pdf"
        return client._download_pdf(
            f"{endpoint}/{value}.pdf",
            filename=filename,
            provider="arxiv",
        )


ARXIV_PROVIDER = ProviderDefinition(
    name="arxiv",
    identifier_aliases=("arxiv",),
    identifier_parser=parse_arxiv,
    auto_detect_identifier=True,
    search_adapter=ArxivSearchAdapter(),
    lookup_adapter=ArxivLookupAdapter(),
    document_adapter=ArxivDocumentAdapter(),
    endpoint="https://export.arxiv.org/api/query",
    document_endpoint="https://arxiv.org/pdf",
)
