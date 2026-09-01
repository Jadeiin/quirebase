from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote, urlencode

from inquiro.canonical import (
    clean_rich_markup,
    collect_urls,
    first_text,
    normalize_reference_type,
)
from inquiro.identifiers import DOI_PATTERN, normalize_doi, parse_openalex
from inquiro.models import (
    AcquiredDocument,
    InvalidProviderRequest,
    PdfNotAvailable,
    ProviderRecord,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition, RemoteNotFound
from inquiro.providers._payload import (
    collect_openalex_keyword_names,
    reconstruct_openalex_abstract,
)


class OpenAlexLookupAdapter:
    async def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        api_key = getattr(settings, "openalex_api_key", None)
        params = {"api_key": api_key} if api_key else None
        lookup_target = f"doi:{value}" if DOI_PATTERN.fullmatch(value) else value
        try:
            body = await client._get(
                f"{endpoint}/works/{quote(lookup_target, safe=':')}",
                params,
            )
        except (RemoteNotFound, ProviderUnavailable):
            if lookup_target.startswith("doi:"):
                body = await client._get(
                    f"{endpoint}/works/https://doi.org/{quote(value, safe='')}",
                    params,
                )
            else:
                raise
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("OpenAlex returned invalid metadata") from error
        openalex_id = (first_text(payload.get("id")) or "").rsplit("/", 1)[-1]
        doi = normalize_doi(first_text(payload.get("doi")) or "") or None
        source = (payload.get("primary_location") or {}).get("source") or {}
        biblio = payload.get("biblio") or {}
        pages = None
        if biblio.get("first_page") and biblio.get("last_page"):
            pages = f"{biblio.get('first_page')}-{biblio.get('last_page')}"
        elif biblio.get("first_page"):
            pages = str(biblio.get("first_page"))

        urls = collect_urls(
            f"https://doi.org/{doi}" if doi else None,
            first_text((payload.get("primary_location") or {}).get("landing_page_url")),
            first_text((payload.get("open_access") or {}).get("oa_url")),
        )

        abstract = reconstruct_openalex_abstract(
            payload.get("abstract_inverted_index")
        ) or clean_rich_markup(first_text(payload.get("abstract")))
        kw_list = collect_openalex_keyword_names(payload.get("topics"), payload.get("keywords"))
        if not kw_list:
            kw_list = collect_openalex_keyword_names(payload.get("concepts"))
        keywords_val = "; ".join(kw_list) if kw_list else None
        title = (
            clean_rich_markup(first_text(payload.get("display_name") or payload.get("title"))) or ""
        )

        return ProviderRecord(
            title=title,
            abstract=abstract,
            authors="; ".join(
                author_name
                for authorship in payload.get("authorships", [])
                if (author_name := first_text((authorship.get("author") or {}).get("display_name")))
            )
            or None,
            keywords=keywords_val,
            publication_date=first_text(payload.get("publication_date")),
            publication_title=first_text(source.get("display_name")),
            volume=first_text(biblio.get("volume")),
            issue=first_text(biblio.get("issue")),
            pages=pages,
            publisher=first_text(source.get("host_organization_name")),
            doi=doi,
            urls=urls,
            identifiers=json.dumps({
                key: val for key, val in {"openalex": openalex_id, "doi": doi}.items() if val
            }),
            reference_type=normalize_reference_type(first_text(payload.get("type"))),
        )


class OpenAlexSearchAdapter:
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
            "page": page,
            "per_page": per_page,
            "sort": "publication_date:desc" if sort == "published" else "relevance_score:desc",
        }
        api_key = getattr(settings, "openalex_api_key", None)
        if api_key:
            params["api_key"] = api_key
        filter_fields = {
            "title": "title.search",
            "author": "raw_author_name.search",
            "abstract": "abstract.search",
            "any": "default.search",
        }
        groups: list[tuple[str, list[str], bool]] = []
        for clause in clauses:
            clean = re.sub(r'[,|!"\\]+', " ", clause.term).strip()
            if clause.operator == "or":
                if not groups or groups[-1][0] != clause.field or groups[-1][2]:
                    raise InvalidProviderRequest(
                        "OpenAlex only supports OR between adjacent conditions on the same field"
                    )
                groups[-1][1].append(clean)
            else:
                groups.append((clause.field, [clean], clause.operator == "not"))
        filter_parts: list[str] = []
        for field, values, negated in groups:
            if field == "publication":
                source_ids: list[str] = []
                for value in values:
                    source_ids.extend(
                        await self._resolve_source_ids(client, value, settings, endpoint)
                    )
                source_ids = list(dict.fromkeys(source_ids))
                if not source_ids:
                    if negated:
                        continue
                    return ProviderSearchPage("openalex", [], 0, page, per_page)
                filter_field = "primary_location.source.id"
                filter_value = "|".join(source_ids)
            else:
                filter_field = filter_fields[field]
                filter_value = "|".join(values)
            filter_parts.append(f"{filter_field}:{'!' if negated else ''}{filter_value}")
        if year_from:
            filter_parts.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filter_parts.append(f"to_publication_date:{year_to}-12-31")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)
        if sort == "relevance" and not any(".search:" in value for value in filter_parts):
            params["sort"] = "cited_by_count:desc"
        body = await client._get(f"{endpoint}/works", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("OpenAlex returned invalid search results") from error
        meta = payload.get("meta", {})
        total = int(meta.get("count", 0))
        results = []
        for work in payload.get("results", []):
            openalex_id = (work.get("id") or "").rsplit("/", 1)[-1]
            title = clean_rich_markup(work.get("display_name") or work.get("title"))
            if not openalex_id or not title:
                continue
            doi = (
                re.sub(
                    r"^https?://(?:dx\.)?doi\.org/", "", work.get("doi") or "", flags=re.IGNORECASE
                )
                or None
            )
            authors = "; ".join(
                author_name
                for authorship in work.get("authorships", [])
                if (author_name := first_text((authorship.get("author") or {}).get("display_name")))
            )
            abstract = reconstruct_openalex_abstract(
                work.get("abstract_inverted_index")
            ) or clean_rich_markup(first_text(work.get("abstract")))
            source = (work.get("primary_location") or {}).get("source") or {}
            results.append(
                ProviderSearchRecord(
                    provider="openalex",
                    identifier_provider="openalex",
                    identifier=openalex_id,
                    title=title,
                    authors=authors or None,
                    publication_title=first_text(source.get("display_name")),
                    publication_date=work.get("publication_date"),
                    doi=doi,
                    abstract=abstract,
                )
            )
        return ProviderSearchPage("openalex", results, total, page, per_page)

    async def _resolve_source_ids(
        self, client: ProviderContext, name: str, settings: Any, endpoint: str
    ) -> list[str]:
        params: dict[str, Any] = {"search": name, "per-page": "10"}
        api_key = getattr(settings, "openalex_api_key", None)
        if api_key:
            params["api_key"] = api_key
        try:
            body = await client._get(f"{endpoint}/sources", params)
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("OpenAlex returned invalid source results") from error
        return [
            source_id
            for source in payload.get("results", [])
            if (source_id := (first_text(source.get("id")) or "").rsplit("/", 1)[-1])
        ]


class OpenAlexDocumentAdapter:
    async def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: Any,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        api_key = settings.openalex_api_key
        work_id = value
        if DOI_PATTERN.fullmatch(value):
            params = {"api_key": api_key, "select": "id,has_content"}
            try:
                body = await client._get(
                    f"https://api.openalex.org/works/{quote(f'doi:{value}', safe=':')}",
                    params,
                )
            except RemoteNotFound as error:
                raise PdfNotAvailable("OpenAlex work was not found") from error
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    raise TypeError
                has_content = payload.get("has_content") or {}
                if not isinstance(has_content, dict):
                    raise TypeError
                work_id = (first_text(payload.get("id")) or "").rsplit("/", 1)[-1]
            except (json.JSONDecodeError, TypeError) as error:
                raise ProviderUnavailable("OpenAlex returned invalid document metadata") from error
            if not work_id or not has_content.get("pdf"):
                raise PdfNotAvailable("OpenAlex does not have a PDF for this work")

        download_url = f"{endpoint}/{work_id}.pdf?{urlencode({'api_key': api_key})}"
        return await client._download_pdf(
            download_url,
            filename=f"{work_id}.pdf",
            provider="openalex",
        )


OPENALEX_PROVIDER = ProviderDefinition(
    name="openalex",
    identifier_aliases=("openalex",),
    identifier_parser=parse_openalex,
    auto_detect_identifier=True,
    search_adapter=OpenAlexSearchAdapter(),
    lookup_adapter=OpenAlexLookupAdapter(),
    document_adapter=OpenAlexDocumentAdapter(),
    endpoint="https://api.openalex.org",
    document_endpoint="https://content.openalex.org/works",
    credential_setting="openalex_api_key",
    credential_environment="INQUIRO_OPENALEX_API_KEY",
    credential_capabilities=frozenset({"document"}),
)
