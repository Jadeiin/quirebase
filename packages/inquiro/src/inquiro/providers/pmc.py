from __future__ import annotations

import json
from typing import Any

from inquiro.models import (
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.parsing import (
    _boolean_query,
    _clean_markup,
    _first,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


class PmcSearchAdapter:
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
        params = {
            "db": "pmc",
            "term": query,
            "retmode": "json",
            "retstart": str((page - 1) * per_page),
            "retmax": str(per_page),
            "sort": "pub date" if sort == "published" else "relevance",
            "tool": "quirebase",
        }
        contact = settings.contact_email
        if contact:
            params["email"] = contact
        api_key = getattr(settings, "ncbi_api_key", None)
        if api_key:
            params["api_key"] = api_key
        try:
            found = json.loads(client._get(f"{endpoint}/esearch.fcgi", params)).get(
                "esearchresult", {}
            )
            identifiers = found.get("idlist", [])
            if not identifiers:
                return ProviderSearchPage("pmc", [], int(found.get("count", 0)), page, per_page)
            summary_params = {
                "db": "pmc",
                "id": ",".join(identifiers),
                "retmode": "json",
                "tool": "quirebase",
            }
            if contact:
                summary_params["email"] = contact
            if api_key:
                summary_params["api_key"] = api_key
            payload = json.loads(client._get(f"{endpoint}/esummary.fcgi", summary_params)).get(
                "result", {}
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("PMC returned invalid search results") from error
        results = []
        for identifier in identifiers:
            record = payload.get(identifier, {})
            title = _clean_markup(record.get("title"))
            if not title:
                continue
            doi = None
            pmid = None
            for article_id in record.get("articleids", []):
                if article_id.get("idtype") == "doi" and article_id.get("value"):
                    doi = article_id["value"]
                elif article_id.get("idtype") == "pmid" and article_id.get("value"):
                    pmid = article_id["value"]
            if doi:
                result_provider, result_identifier = "doi", doi
            elif pmid:
                result_provider, result_identifier = "pmid", pmid
            else:
                continue
            results.append(
                ProviderSearchRecord(
                    provider="pmc",
                    identifier_provider=result_provider,
                    identifier=result_identifier,
                    title=title,
                    authors="; ".join(
                        author["name"] for author in record.get("authors", []) if author.get("name")
                    )
                    or None,
                    publication_title=_first(record.get("fulljournalname") or record.get("source")),
                    publication_date=_first(record.get("pubdate")),
                )
            )
        return ProviderSearchPage(
            "pmc", results, int(found.get("count", len(results))), page, per_page
        )


PMC_PROVIDER = ProviderDefinition(
    name="pmc",
    search_adapter=PmcSearchAdapter(),
    endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
)
