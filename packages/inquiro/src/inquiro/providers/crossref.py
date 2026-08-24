from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from inquiro.identifiers import parse_doi
from inquiro.models import (
    CandidateNotFound,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.parsing import (
    _clean_markup,
    _collect_urls,
    _date_parts,
    _first,
    normalize_reference_type,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


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
                    _clean_markup(_first(author.get("family"))),
                    _clean_markup(_first(author.get("given"))),
                )
                if part
            )
            for author in message.get("author", [])
            if isinstance(author, dict)
        )
        canonical_doi = _first(message.get("DOI")) or value

        affiliations: list[str] = []
        for author in message.get("author", []):
            if not isinstance(author, dict):
                continue
            for affiliation in author.get("affiliation", []):
                if not isinstance(affiliation, dict):
                    continue
                name = _clean_markup(_first(affiliation.get("name")))
                if name and name not in affiliations:
                    affiliations.append(name)

        resource = message.get("resource") or {}
        primary_resource = resource.get("primary") or {}
        urls = _collect_urls(
            f"https://doi.org/{canonical_doi}",
            _first(message.get("URL")),
            _first(primary_resource.get("URL")),
            *(
                _first(link.get("URL"))
                for link in message.get("link", [])
                if isinstance(link, dict)
            ),
        )
        keywords = "; ".join(
            keyword
            for subject in message.get("subject", [])
            if (keyword := _clean_markup(_first(subject)))
        )
        return ProviderRecord(
            title=_clean_markup(_first(message.get("title"))) or "",
            abstract=_clean_markup(_first(message.get("abstract"))),
            authors=authors or None,
            keywords=keywords or None,
            publication_date=_date_parts(message),
            publication_title=_clean_markup(_first(message.get("container-title"))),
            journal_abbreviation=_clean_markup(_first(message.get("short-container-title"))),
            volume=_clean_markup(_first(message.get("volume"))),
            issue=_clean_markup(
                _first(message.get("issue") or (message.get("journal-issue") or {}).get("issue"))
            ),
            pages=_clean_markup(_first(message.get("page"))),
            publisher=_clean_markup(_first(message.get("publisher"))),
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
            doi = _first(item.get("DOI"))
            if not doi:
                continue
            authors = "; ".join(
                ", ".join(
                    part
                    for part in (
                        _clean_markup(_first(author.get("family"))),
                        _clean_markup(_first(author.get("given"))),
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
                    title=_clean_markup(_first(item.get("title"))) or "",
                    authors=authors or None,
                    publication_title=_clean_markup(_first(item.get("container-title"))),
                    publication_date=_date_parts(item),
                    doi=doi,
                    abstract=_clean_markup(_first(item.get("abstract"))),
                )
            )
        return ProviderSearchPage("crossref", results, total, page, per_page)


CROSSREF_PROVIDER = ProviderDefinition(
    name="crossref",
    identifier_aliases=("doi", "crossref"),
    identifier_parser=parse_doi,
    auto_detect_identifier=True,
    search_adapter=CrossrefSearchAdapter(),
    lookup_adapter=CrossrefLookupAdapter(),
    endpoint="https://api.crossref.org/works",
)
