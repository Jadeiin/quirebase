from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from inquiro.canonical import clean_rich_markup, first_text
from inquiro.identifiers import DOI_PATTERN, parse_openalex
from inquiro.models import (
    AcquiredDocument,
    CandidatePage,
    CandidateRecord,
    Identifier,
    InvalidProviderRequest,
    PdfNotAvailable,
    ProviderConfig,
    ProviderRateLimited,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition, RemoteNotFound
from inquiro.work import read_work

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _record(payload: dict, identifier: Identifier) -> CandidateRecord:
    return CandidateRecord(
        provider="openalex",
        lookup_identifier=identifier,
        work=read_work(payload, "openalex"),
        diagnostics=(
            "Commonmeta's OpenAlex reader does not retain corresponding-author flags or raw affiliation text; file links come from best_oa_location.",
        ),
    )


class OpenAlexLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        api_key = settings.openalex_api_key
        params = {"api_key": api_key} if api_key else None
        lookup_target = f"doi:{value}" if DOI_PATTERN.fullmatch(value) else value
        try:
            body = await client.get(f"{endpoint}/works/{quote(lookup_target, safe=':')}", params)
        except ProviderRateLimited:
            raise
        except (RemoteNotFound, ProviderUnavailable):
            if lookup_target.startswith("doi:"):
                body = await client.get(
                    f"{endpoint}/works/https://doi.org/{quote(value, safe='')}", params
                )
            else:
                raise
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("OpenAlex returned invalid metadata") from error
        return _record(payload, identifier)


class OpenAlexSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        params: dict[str, Any] = {
            "page": request.page,
            "per_page": request.per_page,
            "sort": {"published": "publication_date:desc", "cited": "cited_by_count:desc"}.get(
                request.sort, "relevance_score:desc"
            ),
        }
        api_key = settings.openalex_api_key
        if api_key:
            params["api_key"] = api_key
        filter_fields = {
            "title": "title.search",
            "author": "raw_author_name.search",
            "abstract": "abstract.search",
            "any": "default.search",
        }
        groups: list[tuple[str, list[str], bool]] = []
        for clause in request.clauses:
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
                    return CandidatePage("openalex", (), 0, request.page, request.per_page)
                filter_field = "primary_location.source.id"
                filter_value = "|".join(source_ids)
            else:
                filter_field = filter_fields[field]
                filter_value = "|".join(values)
            filter_parts.append(f"{filter_field}:{('!' if negated else '')}{filter_value}")
        if request.year_from:
            filter_parts.append(f"from_publication_date:{request.year_from}-01-01")
        if request.year_to:
            filter_parts.append(f"to_publication_date:{request.year_to}-12-31")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)
        if request.sort == "relevance" and (not any(".search:" in value for value in filter_parts)):
            params["sort"] = "cited_by_count:desc"
        body = await client.get(f"{endpoint}/works", params)
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
            results.append(_record(work, Identifier("openalex", openalex_id.upper())))
        return CandidatePage("openalex", tuple(results), total, request.page, request.per_page)

    async def _resolve_source_ids(
        self, client: BoundedTransport, name: str, settings: ProviderConfig, endpoint: str
    ) -> list[str]:
        params: dict[str, Any] = {"search": name, "per-page": "10"}
        api_key = settings.openalex_api_key
        if api_key:
            params["api_key"] = api_key
        try:
            body = await client.get(f"{endpoint}/sources", params)
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
        self, client: BoundedTransport, value: str, settings: ProviderConfig, *, endpoint: str
    ) -> AcquiredDocument:
        api_key = settings.openalex_api_key
        work_id = value
        if DOI_PATTERN.fullmatch(value):
            params = {"api_key": api_key, "select": "id,has_content"}
            try:
                body = await client.get(
                    f"https://api.openalex.org/works/{quote(f'doi:{value}', safe=':')}", params
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
        return await client.download_pdf(
            download_url, filename=f"{work_id}.pdf", provider="openalex"
        )


OPENALEX_PROVIDER = ProviderDefinition(
    name="openalex",
    display_name="OpenAlex",
    identifier_namespace="openalex",
    additional_lookup_namespaces=("doi",),
    identifier_parser=parse_openalex,
    auto_detect_identifier=True,
    search_adapter=OpenAlexSearchAdapter(),
    search_sorts=("relevance", "published", "cited"),
    lookup_adapter=OpenAlexLookupAdapter(),
    document_adapter=OpenAlexDocumentAdapter(),
    endpoint="https://api.openalex.org",
    document_endpoint="https://content.openalex.org/works",
    credential_setting="openalex_api_key",
    credential_environment="INQUIRO_OPENALEX_API_KEY",
    credential_capabilities=frozenset({"document"}),
)
