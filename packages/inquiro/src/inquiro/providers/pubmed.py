from __future__ import annotations

import json
from typing import Any

from inquiro.identifiers import parse_pmid
from inquiro.models import (
    CandidateNotFound,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.parsing import (
    _boolean_query,
    _clean_markup,
    _collect_urls,
    _first,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


class PubMedLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        params = {"db": "pubmed", "id": value, "retmode": "json", "tool": "inquiro"}
        contact = settings.contact_email
        if contact:
            params["email"] = contact
        api_key = getattr(settings, "ncbi_api_key", None)
        if api_key:
            params["api_key"] = api_key
        body = client._get(f"{endpoint}/esummary.fcgi", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("PubMed returned invalid metadata") from error
        result = payload.get("result", {})
        item = result.get(value)
        if not item or not item.get("title"):
            raise CandidateNotFound("PubMed article was not found")
        authors = "; ".join(
            author.get("name", "") for author in item.get("authors", []) if author.get("name")
        )
        doi = next(
            (art.get("value") for art in item.get("articleids", []) if art.get("idtype") == "doi"),
            None,
        )
        identifiers: dict[str, str] = {"pmid": value}
        urls = _collect_urls(
            f"https://pubmed.ncbi.nlm.nih.gov/{value}/",
            f"https://doi.org/{doi}" if doi else None,
        )
        if doi:
            identifiers["doi"] = doi
        return ProviderRecord(
            title=_clean_markup(item.get("title")) or "",
            abstract=None,
            authors=authors or None,
            keywords=None,
            publication_date=item.get("pubdate"),
            publication_title=_first(item.get("fulljournalname") or item.get("source")),
            journal_abbreviation=_first(item.get("source")),
            volume=_first(item.get("volume")),
            issue=_first(item.get("issue")),
            pages=_first(item.get("pages")),
            publisher=_first(item.get("publishername")),
            doi=doi,
            urls=urls,
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class PubMedSearchAdapter:
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
                "any": "[All Fields]",
                "title": "[Title]",
                "author": "[Author]",
                "publication": "[Journal]",
                "abstract": "[Title/Abstract]",
            },
        )
        if year_from or year_to:
            query += f" AND {year_from or 1000}:{year_to or 3000}[Publication Date]"
        search_params = {
            "db": "pubmed",
            "term": query,
            "retstart": str((page - 1) * per_page),
            "retmax": str(per_page),
            "retmode": "json",
            "sort": "pub date" if sort == "published" else "relevance",
            "tool": "inquiro",
        }
        contact = settings.contact_email
        if contact:
            search_params["email"] = contact
        api_key = getattr(settings, "ncbi_api_key", None)
        if api_key:
            search_params["api_key"] = api_key
        search_body = client._get(f"{endpoint}/esearch.fcgi", search_params)
        try:
            search_data = json.loads(search_body).get("esearchresult", {})
            ids = search_data.get("idlist", [])
            total = int(search_data.get("count", 0))
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ProviderUnavailable("PubMed returned invalid search results") from error
        if not ids:
            return ProviderSearchPage("pubmed", [], total, page, per_page)
        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": "inquiro",
        }
        if contact:
            summary_params["email"] = contact
        if api_key:
            summary_params["api_key"] = api_key
        summary_body = client._get(f"{endpoint}/esummary.fcgi", summary_params)
        try:
            summary_data = json.loads(summary_body).get("result", {})
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("PubMed returned invalid summaries") from error
        results = []
        for pmid in ids:
            item = summary_data.get(pmid, {})
            title = _clean_markup(item.get("title"))
            if not title:
                continue
            authors = "; ".join(
                author.get("name", "") for author in item.get("authors", []) if author.get("name")
            )
            results.append(
                ProviderSearchRecord(
                    provider="pubmed",
                    identifier_provider="pmid",
                    identifier=pmid,
                    title=title,
                    authors=authors or None,
                    publication_title=item.get("source"),
                    publication_date=item.get("pubdate"),
                    doi=next(
                        (
                            art.get("value")
                            for art in item.get("articleids", [])
                            if art.get("idtype") == "doi"
                        ),
                        None,
                    ),
                )
            )
        return ProviderSearchPage("pubmed", results, total, page, per_page)


PUBMED_PROVIDER = ProviderDefinition(
    name="pubmed",
    identifier_aliases=("pmid", "pubmed"),
    identifier_parser=parse_pmid,
    auto_detect_identifier=True,
    search_adapter=PubMedSearchAdapter(),
    lookup_adapter=PubMedLookupAdapter(),
    endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
)
