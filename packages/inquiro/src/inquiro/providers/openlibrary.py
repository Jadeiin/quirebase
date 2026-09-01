from __future__ import annotations

import json
from typing import Any

from inquiro.canonical import (
    first_text,
)
from inquiro.identifiers import parse_isbn
from inquiro.models import (
    CandidateNotFound,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition
from inquiro.providers._payload import (
    boolean_query,
)


class OpenLibraryLookupAdapter:
    async def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        key = f"ISBN:{value}"
        try:
            payload = json.loads(
                await client._get(
                    f"{endpoint}/api/books",
                    {"bibkeys": key, "format": "json", "jscmd": "data"},
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("Open Library returned invalid metadata") from error
        record = payload.get(key)
        if not record:
            raise CandidateNotFound("Open Library record was not found")
        return ProviderRecord(
            title=first_text(record.get("title")) or "",
            abstract=None,
            authors="; ".join(
                author["name"] for author in record.get("authors", []) if author.get("name")
            )
            or None,
            keywords=None,
            publication_date=first_text(record.get("publish_date")),
            publication_title=first_text([
                publisher.get("name") for publisher in record.get("publishers", [])
            ]),
            doi=None,
            urls=f"https://openlibrary.org/isbn/{value}",
            identifiers=json.dumps({"isbn": value}),
            reference_type="book",
        )


class OpenLibrarySearchAdapter:
    async def search(
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
            "limit": str(per_page),
            "offset": str((page - 1) * per_page),
            "fields": "key,title,author_name,publisher,first_publish_year,isbn",
            "q": boolean_query(
                clauses,
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
        if year_from or year_to:
            params["first_publish_year"] = f"[{year_from or 0} TO {year_to or 3000}]"
        if sort == "published":
            params["sort"] = "new"
        body = await client._get(f"{endpoint}/search.json", params)
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
                ProviderSearchRecord(
                    provider="openlibrary",
                    identifier_provider="isbn",
                    identifier=isbns[0],
                    title=doc.get("title"),
                    authors="; ".join(doc.get("author_name", [])) or None,
                    publication_title=first_text(doc.get("publisher")),
                    publication_date=str(doc.get("first_publish_year") or "") or None,
                )
            )
        return ProviderSearchPage("openlibrary", results, total, page, per_page)


OPENLIBRARY_PROVIDER = ProviderDefinition(
    name="openlibrary",
    identifier_aliases=("isbn",),
    identifier_parser=parse_isbn,
    auto_detect_identifier=True,
    search_adapter=OpenLibrarySearchAdapter(),
    lookup_adapter=OpenLibraryLookupAdapter(),
    endpoint="https://openlibrary.org",
)
