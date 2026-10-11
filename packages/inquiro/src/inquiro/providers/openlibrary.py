from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from inquiro.canonical import (
    first_text,
)
from inquiro.identifiers import parse_isbn
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
    boolean_query,
    keyword_values,
    text_contributors,
    unique_links,
)
from inquiro.reference_types import ReferenceType

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _links(record: dict, value: str) -> tuple[ResourceLink, ...]:
    links = [
        ResourceLink(
            first_text(record.get("url")) or f"https://openlibrary.org/isbn/{value}",
            kind="landing_page",
        )
    ]
    media_types = {
        "pdf": "application/pdf",
        "epub": "application/epub+zip",
        "text": "text/plain",
        "djvu": "image/vnd.djvu",
    }
    for ebook in record.get("ebooks", []):
        if url := first_text(ebook.get("preview_url")):
            links.append(ResourceLink(url, kind="landing_page"))
        for format_name, entry in (ebook.get("formats") or {}).items():
            if isinstance(entry, dict) and (url := first_text(entry.get("url"))):
                links.append(
                    ResourceLink(url, kind="full_text", media_type=media_types.get(format_name))
                )
    return unique_links(*links)


class OpenLibraryLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        key = f"ISBN:{value}"
        try:
            payload = json.loads(
                await client.get(
                    f"{endpoint}/api/books",
                    {"bibkeys": key, "format": "json", "jscmd": "data"},
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Open Library returned invalid metadata") from error
        record = payload.get(key)
        if not record:
            raise CandidateNotFound("Open Library record was not found")
        return CandidateRecord(
            provider="openlibrary",
            lookup_identifier=identifier,
            title=first_text(record.get("title")) or "",
            abstract=None,
            authors=tuple(
                Contributor(
                    name,
                    identifiers=(Identifier("openlibrary", url),)
                    if (url := first_text(author.get("url")))
                    else (),
                )
                for author in record.get("authors", [])
                if (name := first_text(author.get("name")))
            )
            if "authors" in record
            else None,
            keywords=keyword_values([
                entry["name"] for entry in record["subjects"] if entry.get("name")
            ])
            if "subjects" in record
            else None,
            publication_date=first_text(record.get("publish_date")),
            publisher=first_text([
                publisher.get("name") for publisher in record.get("publishers", [])
            ]),
            urls=_links(record, value),
            identifiers=(Identifier("isbn", value),),
            reference_type=ReferenceType.book,
        )


class OpenLibrarySearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        params: dict[str, Any] = {
            "limit": str(request.per_page),
            "offset": str((request.page - 1) * request.per_page),
            "fields": "key,title,author_name,publisher,first_publish_year,isbn",
            "q": boolean_query(
                request.clauses,
                {
                    "any": "",
                    "title": "title:",
                    "author": "author:",
                    "publication": "publisher:",
                    "abstract": "",
                },
                field_prefix=True,
            ),
        }
        if request.year_from or request.year_to:
            params["first_publish_year"] = (
                f"[{request.year_from or 0} TO {request.year_to or 3000}]"
            )
        if request.sort == "published":
            params["sort"] = "new"
        body = await client.get(f"{endpoint}/search.json", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Open Library returned invalid search results") from error
        total = int(payload.get("numFound", 0))
        results = []
        for doc in payload.get("docs", []):
            isbns = doc.get("isbn", [])
            if not isbns or not doc.get("title"):
                continue
            results.append(
                CandidateRecord(
                    provider="openlibrary",
                    lookup_identifier=Identifier("isbn", isbns[0]),
                    identifiers=(Identifier("isbn", isbns[0]),),
                    title=doc.get("title"),
                    authors=text_contributors(doc.get("author_name")),
                    publication_title=first_text(doc.get("publisher")),
                    publication_date=str(doc.get("first_publish_year") or "") or None,
                )
            )
        return CandidatePage("openlibrary", tuple(results), total, request.page, request.per_page)


OPENLIBRARY_PROVIDER = ProviderDefinition(
    name="openlibrary",
    identifier_namespace="isbn",
    identifier_parser=parse_isbn,
    auto_detect_identifier=True,
    search_adapter=OpenLibrarySearchAdapter(),
    lookup_adapter=OpenLibraryLookupAdapter(),
    endpoint="https://openlibrary.org",
)
