from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from inquiro.canonical import (
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import DOI_PATTERN, OPENALEX_PATTERN, normalize_doi, parse_openalex
from inquiro.models import (
    AcquiredDocument,
    Affiliation,
    CandidatePage,
    CandidateRecord,
    Contributor,
    Identifier,
    InvalidProviderRequest,
    PdfNotAvailable,
    ProviderConfig,
    ProviderUnavailable,
    ResourceLink,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition, RemoteNotFound
from inquiro.providers._payload import (
    collect_openalex_keyword_names,
    reconstruct_openalex_abstract,
    unique_links,
)
from inquiro.reference_types import normalize_reference_type

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _institution_affiliation(institution: dict, raw: str | None = None) -> Affiliation | None:
    if not (name := first_text(institution.get("display_name"))):
        return None
    identities = []
    if identity := first_text(institution.get("id")):
        identities.append(Identifier("openalex", identity))
    if ror := first_text(institution.get("ror")):
        identities.append(Identifier("ror", ror))
    return Affiliation(name, tuple(identities), first_text(institution.get("country_code")), raw)


def _affiliations(authorship: dict) -> tuple[Affiliation, ...] | None:
    if not any(
        key in authorship for key in ("institutions", "affiliations", "raw_affiliation_strings")
    ):
        return None
    institutions = [
        entry for entry in authorship.get("institutions", []) if isinstance(entry, dict)
    ]
    institutions_by_id = {
        identity: entry for entry in institutions if (identity := first_text(entry.get("id")))
    }
    affiliations = []
    referenced: set[str] = set()
    raw_names = set()
    for entry in authorship.get("affiliations", []):
        raw = first_text(entry.get("raw_affiliation_string"))
        if raw:
            raw_names.add(raw)
        matches = [
            institutions_by_id[value]
            for value in entry.get("institution_ids", [])
            if value in institutions_by_id
        ]
        mapped = [
            affiliation
            for institution in matches
            if (affiliation := _institution_affiliation(institution, raw))
        ]
        if not mapped and raw:
            affiliations.append(Affiliation(raw))
        referenced.update(institution["id"] for institution in matches)
        affiliations.extend(mapped)
    affiliations.extend(
        affiliation
        for institution in institutions
        if institution.get("id") not in referenced
        and (affiliation := _institution_affiliation(institution))
    )
    affiliations.extend(
        Affiliation(name)
        for raw in authorship.get("raw_affiliation_strings", [])
        if (name := first_text(raw)) and name not in raw_names
    )
    return tuple(dict.fromkeys(affiliations))


def _contributors(payload: dict) -> tuple[Contributor, ...] | None:
    if not isinstance(payload.get("authorships"), list):
        return None
    authors = []
    for authorship in payload["authorships"]:
        author = authorship.get("author") or {}
        name = first_text(author.get("display_name")) or first_text(
            authorship.get("raw_author_name")
        )
        if not name:
            continue
        identities = []
        if value := first_text(author.get("id")):
            identities.append(Identifier("openalex", value))
        if value := first_text(author.get("orcid")):
            identities.append(Identifier("orcid", value))
        corresponding = authorship.get("is_corresponding")
        authors.append(
            Contributor(
                display_name=name,
                identifiers=tuple(identities),
                affiliations=_affiliations(authorship),
                is_corresponding=corresponding if isinstance(corresponding, bool) else None,
            )
        )
    return tuple(authors)


def _links(payload: dict, doi: str | None) -> tuple[ResourceLink, ...]:
    links = []
    locations = [
        payload.get("primary_location"),
        payload.get("best_oa_location"),
        *payload.get("locations", []),
    ]
    for location in locations:
        if not isinstance(location, dict):
            continue
        is_oa = location.get("is_oa")
        version = first_text(location.get("version"))
        license = first_text(location.get("license"))
        access = is_oa if isinstance(is_oa, bool) else None
        if url := first_text(location.get("landing_page_url")):
            links.append(
                ResourceLink(
                    url,
                    kind="landing_page",
                    version=version,
                    license=license,
                    is_open_access=access,
                )
            )
        if url := first_text(location.get("pdf_url")):
            links.append(
                ResourceLink(
                    url,
                    kind="full_text",
                    media_type="application/pdf",
                    version=version,
                    license=license,
                    is_open_access=access,
                )
            )
    if doi and not any(link.url == f"https://doi.org/{doi}" for link in links):
        links.insert(0, ResourceLink(f"https://doi.org/{doi}", kind="landing_page"))
    if (url := first_text((payload.get("open_access") or {}).get("oa_url"))) and not any(
        link.url == url for link in links
    ):
        links.append(ResourceLink(url, is_open_access=True))
    return unique_links(*links)


def _record(payload: dict, identifier: Identifier) -> CandidateRecord:
    openalex_id = (first_text(payload.get("id")) or "").rsplit("/", 1)[-1]
    if not OPENALEX_PATTERN.fullmatch(openalex_id):
        raise ProviderUnavailable("OpenAlex returned metadata without a valid Work ID")
    openalex_id = openalex_id.upper()
    doi = normalize_doi(first_text(payload.get("doi")) or "") or None
    source = (payload.get("primary_location") or {}).get("source") or {}
    biblio = payload.get("biblio") or {}
    pages = None
    if biblio.get("first_page") and biblio.get("last_page"):
        pages = f"{biblio.get('first_page')}-{biblio.get('last_page')}"
    elif biblio.get("first_page"):
        pages = str(biblio.get("first_page"))

    abstract = reconstruct_openalex_abstract(
        payload.get("abstract_inverted_index")
    ) or clean_rich_markup(first_text(payload.get("abstract")))
    kw_list = collect_openalex_keyword_names(payload.get("topics"), payload.get("keywords"))
    if not kw_list:
        kw_list = collect_openalex_keyword_names(payload.get("concepts"))
    title = clean_rich_markup(first_text(payload.get("display_name") or payload.get("title"))) or ""

    return CandidateRecord(
        provider="openalex",
        lookup_identifier=identifier,
        title=title,
        abstract=abstract,
        authors=_contributors(payload),
        keywords=tuple(kw_list) if kw_list else None,
        publication_date=first_text(payload.get("publication_date")),
        publication_title=first_text(source.get("display_name")),
        volume=first_text(biblio.get("volume")),
        issue=first_text(biblio.get("issue")),
        pages=pages,
        publisher=first_text(source.get("host_organization_name")),
        doi=doi,
        urls=_links(payload, doi),
        identifiers=tuple(
            Identifier(key, val)
            for key, val in {"openalex": openalex_id, "doi": doi}.items()
            if val
        ),
        reference_type=normalize_reference_type(first_text(payload.get("type")), source="openalex"),
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
            body = await client.get(
                f"{endpoint}/works/{quote(lookup_target, safe=':')}",
                params,
            )
        except (RemoteNotFound, ProviderUnavailable):
            if lookup_target.startswith("doi:"):
                body = await client.get(
                    f"{endpoint}/works/https://doi.org/{quote(value, safe='')}",
                    params,
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
            "sort": "publication_date:desc"
            if request.sort == "published"
            else "relevance_score:desc",
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
                    return CandidatePage("openalex", [], 0, request.page, request.per_page)
                filter_field = "primary_location.source.id"
                filter_value = "|".join(source_ids)
            else:
                filter_field = filter_fields[field]
                filter_value = "|".join(values)
            filter_parts.append(f"{filter_field}:{'!' if negated else ''}{filter_value}")
        if request.year_from:
            filter_parts.append(f"from_publication_date:{request.year_from}-01-01")
        if request.year_to:
            filter_parts.append(f"to_publication_date:{request.year_to}-12-31")
        if filter_parts:
            params["filter"] = ",".join(filter_parts)
        if request.sort == "relevance" and not any(".search:" in value for value in filter_parts):
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
        self,
        client: BoundedTransport,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        api_key = settings.openalex_api_key
        work_id = value
        if DOI_PATTERN.fullmatch(value):
            params = {"api_key": api_key, "select": "id,has_content"}
            try:
                body = await client.get(
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
        return await client.download_pdf(
            download_url,
            filename=f"{work_id}.pdf",
            provider="openalex",
        )


OPENALEX_PROVIDER = ProviderDefinition(
    name="openalex",
    identifier_namespace="openalex",
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
