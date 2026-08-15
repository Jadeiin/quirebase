from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from xml.etree import ElementTree

import httpx

from quirebase.core.config import Settings, get_settings
from quirebase.discovery.lookup import MetadataLookupError, _clean_markup, _date_parts, _first

SEARCH_PROVIDERS = {"crossref", "pubmed", "pmc", "arxiv", "openlibrary", "openalex", "nasa", "ieee"}
SEARCH_FIELDS = {"any", "title", "author", "publication", "abstract"}
SEARCH_OPERATORS = {"and", "or", "not"}


@dataclass(frozen=True)
class SearchClause:
    field: str
    operator: str
    term: str


@dataclass(frozen=True)
class SearchResult:
    provider: str
    identifier_provider: str
    identifier: str
    title: str
    authors: str | None = None
    publication_title: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    abstract: str | None = None


@dataclass(frozen=True)
class SearchPage:
    provider: str
    results: list[SearchResult]
    total: int
    page: int
    per_page: int


class SearchAdapter(Protocol):
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage: ...


def _boolean_query(
    clauses: list[SearchClause], fields: dict[str, str], *, field_prefix: bool = False
) -> str:
    parts: list[str] = []
    for index, clause in enumerate(clauses):
        value = clause.term.replace('"', " ").replace("\\", " ").strip()
        field = fields.get(clause.field, fields["any"])
        tagged = f'{field}"{value}"' if field_prefix else f'"{value}"{field}'
        if clause.operator == "not":
            parts.append(f"NOT {tagged}")
        elif index and clause.operator == "or":
            parts.append(f"OR {tagged}")
        else:
            parts.append(("AND " if index else "") + tagged)
    return " ".join(parts)


class CrossrefSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
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
        if settings.metadata_contact_email:
            params["mailto"] = settings.metadata_contact_email
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
        body = client._get("https://api.crossref.org/works", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid metadata") from error
        message = payload.get("message", {})
        total = int(message.get("total-results", 0))
        results = []
        for item in message.get("items", []):
            doi = item.get("DOI")
            if not doi or not item.get("title"):
                continue
            authors = "; ".join(
                " ".join(part for part in [author.get("given"), author.get("family")] if part)
                for author in item.get("author", [])
                if any([author.get("given"), author.get("family")])
            )
            results.append(
                SearchResult(
                    provider="crossref",
                    identifier_provider="doi",
                    identifier=doi,
                    title=_clean_markup(_first(item.get("title"))) or "",
                    authors=authors or None,
                    publication_title=_first(item.get("container-title")),
                    publication_date=_date_parts(item),
                    doi=doi,
                )
            )
        return SearchPage("crossref", results, total, page, per_page)


class PubMedSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
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
            "tool": "quirebase",
        }
        if settings.metadata_contact_email:
            search_params["email"] = settings.metadata_contact_email
        if settings.ncbi_api_key:
            search_params["api_key"] = settings.ncbi_api_key
        search_body = client._get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", search_params
        )
        try:
            search_data = json.loads(search_body).get("esearchresult", {})
            ids = search_data.get("idlist", [])
            total = int(search_data.get("count", 0))
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise MetadataLookupError("PubMed returned invalid search results") from error
        if not ids:
            return SearchPage("pubmed", [], total, page, per_page)
        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json",
            "tool": "quirebase",
        }
        if settings.metadata_contact_email:
            summary_params["email"] = settings.metadata_contact_email
        if settings.ncbi_api_key:
            summary_params["api_key"] = settings.ncbi_api_key
        summary_body = client._get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", summary_params
        )
        try:
            summary_data = json.loads(summary_body).get("result", {})
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("PubMed returned invalid summaries") from error
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
                SearchResult(
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
        return SearchPage("pubmed", results, total, page, per_page)


class ArxivSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
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
        body = client._get("https://export.arxiv.org/api/query", params)
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise MetadataLookupError("arXiv returned invalid XML") from error
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
                SearchResult(
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
        return SearchPage("arxiv", results, total, page, per_page)


class OpenLibrarySearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
        params: dict[str, Any] = {
            "limit": str(per_page),
            "offset": str((page - 1) * per_page),
            "fields": "key,title,author_name,publisher,first_publish_year,isbn",
            "q": _boolean_query(
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
        body = client._get("https://openlibrary.org/search.json", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Open Library returned invalid search results") from error
        total = int(payload.get("numFound", 0))
        results = []
        for doc in payload.get("docs", []):
            isbns = doc.get("isbn", [])
            if not isbns or not doc.get("title"):
                continue
            results.append(
                SearchResult(
                    provider="openlibrary",
                    identifier_provider="isbn",
                    identifier=isbns[0],
                    title=doc.get("title"),
                    authors="; ".join(doc.get("author_name", [])) or None,
                    publication_title=_first(doc.get("publisher")),
                    publication_date=str(doc.get("first_publish_year") or "") or None,
                )
            )
        return SearchPage("openlibrary", results, total, page, per_page)


class OpenAlexSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
        params: dict[str, Any] = {
            "page": page,
            "per_page": per_page,
            "sort": "publication_date:desc" if sort == "published" else "relevance_score:desc",
        }
        if settings.openalex_api_key:
            params["api_key"] = settings.openalex_api_key
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
                    raise ValueError(
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
                    source_ids.extend(self._resolve_source_ids(client, value, settings))
                source_ids = list(dict.fromkeys(source_ids))
                if not source_ids:
                    if negated:
                        continue
                    return SearchPage("openalex", [], 0, page, per_page)
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
        body = client._get("https://api.openalex.org/works", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid search results") from error
        meta = payload.get("meta", {})
        total = int(meta.get("count", 0))
        results = []
        for work in payload.get("results", []):
            openalex_id = (work.get("id") or "").rsplit("/", 1)[-1]
            title = work.get("display_name") or work.get("title")
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
                if (author_name := _first((authorship.get("author") or {}).get("display_name")))
            )
            source = (work.get("primary_location") or {}).get("source") or {}
            results.append(
                SearchResult(
                    provider="openalex",
                    identifier_provider="openalex",
                    identifier=openalex_id,
                    title=title,
                    authors=authors or None,
                    publication_title=_first(source.get("display_name")),
                    publication_date=work.get("publication_date"),
                    doi=doi,
                )
            )
        return SearchPage("openalex", results, total, page, per_page)

    def _resolve_source_ids(
        self, client: OnlineSearchClient, name: str, settings: Settings
    ) -> list[str]:
        params: dict[str, Any] = {"search": name, "per-page": "10"}
        if settings.openalex_api_key:
            params["api_key"] = settings.openalex_api_key
        try:
            body = client._get("https://api.openalex.org/sources", params)
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid source results") from error
        return [
            source_id
            for source in payload.get("results", [])
            if (source_id := (_first(source.get("id")) or "").rsplit("/", 1)[-1])
        ]


_IEEE_FIELDS = {
    "any": None,
    "title": '"Document Title"',
    "author": '"Author"',
    "publication": '"Publication Title"',
    "abstract": '"Abstract"',
}


def _ieee_boolean_query(clauses: list[SearchClause]) -> str:
    parts = []
    for index, clause in enumerate(clauses):
        value = clause.term.replace('"', " ").replace("\\", " ").strip()
        field = _IEEE_FIELDS[clause.field]
        tagged = f"{field}:{value}" if field else value
        if clause.operator == "not":
            parts.append(f"NOT {tagged}")
        elif index and clause.operator == "or":
            parts.append(f"OR {tagged}")
        else:
            parts.append(("AND " if index else "") + tagged)
    return " ".join(parts)


class PmcSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
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
        if settings.metadata_contact_email:
            params["email"] = settings.metadata_contact_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        try:
            found = json.loads(
                client._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params)
            ).get("esearchresult", {})
            identifiers = found.get("idlist", [])
            if not identifiers:
                return SearchPage("pmc", [], int(found.get("count", 0)), page, per_page)
            payload = json.loads(
                client._get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    {
                        "db": "pmc",
                        "id": ",".join(identifiers),
                        "retmode": "json",
                        "tool": "quirebase",
                    },
                )
            ).get("result", {})
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("PMC returned invalid search results") from error
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
                SearchResult(
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
        return SearchPage("pmc", results, int(found.get("count", len(results))), page, per_page)


class NasaAdsSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
        if not settings.nasa_ads_token:
            raise MetadataLookupError("NASA ADS requires QUIREBASE_NASA_ADS_TOKEN")
        query = _boolean_query(
            clauses,
            {
                "any": "",
                "title": "title:",
                "author": "author:",
                "publication": "bibstem:",
                "abstract": "abs:",
            },
            field_prefix=True,
        )
        if year_from or year_to:
            query += f" year:{year_from or 0}-{year_to or 3000}"
        sort_value = (
            "date desc"
            if sort == "published"
            else "citation_count desc"
            if sort == "cited"
            else "score desc"
        )
        params = {
            "q": query,
            "fl": "bibcode,title,author,doi,pubdate,pub,abstract",
            "rows": str(per_page),
            "start": str((page - 1) * per_page),
            "sort": sort_value,
        }
        headers = {"Authorization": f"Bearer {settings.nasa_ads_token}"}
        try:
            payload = json.loads(
                client._get("https://api.adsabs.harvard.edu/v1/search/query", params, headers=headers)
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("NASA ADS returned invalid search results") from error
        response = payload.get("response", {})
        results = []
        for document in response.get("docs", []):
            title = _first(document.get("title"))
            bibcode = _first(document.get("bibcode"))
            doi = _first(document.get("doi"))
            if not title or not (doi or bibcode):
                continue
            identifier = doi or bibcode
            assert identifier is not None
            results.append(
                SearchResult(
                    provider="nasa",
                    identifier_provider="doi" if doi else "bibcode",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(document.get("author", [])) or None,
                    publication_title=_first(document.get("pub")),
                    publication_date=_first(document.get("pubdate")),
                    abstract=_first(document.get("abstract")),
                )
            )
        return SearchPage(
            "nasa", results, int(response.get("numFound", len(results))), page, per_page
        )


class IeeeSearchAdapter:
    def search(
        self,
        client: OnlineSearchClient,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Settings,
    ) -> SearchPage:
        if not settings.ieee_api_key:
            raise MetadataLookupError("IEEE Xplore requires QUIREBASE_IEEE_API_KEY")
        params = {
            "apikey": settings.ieee_api_key,
            "format": "json",
            "querytext": _ieee_boolean_query(clauses),
            "startRecord": str((page - 1) * per_page + 1),
            "max_records": str(per_page),
        }
        if year_from:
            params["start_year"] = str(year_from)
        if year_to:
            params["end_year"] = str(year_to)
        if sort == "published":
            params["sort_field"] = "publication_year"
            params["sort_order"] = "desc"
        elif sort == "cited":
            params["sort_field"] = "article_citations"
            params["sort_order"] = "desc"
        try:
            payload = json.loads(
                client._get("https://ieeexploreapi.ieee.org/api/v1/search/articles", params)
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("IEEE Xplore returned invalid search results") from error
        results = []
        for article in payload.get("articles", []):
            title = _first(article.get("title"))
            if not title:
                continue
            doi = _first(article.get("doi"))
            article_number = _first(article.get("article_number"))
            identifier = doi or article_number
            if identifier is None:
                continue
            results.append(
                SearchResult(
                    provider="ieee",
                    identifier_provider="doi" if doi else "article_number",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(
                        author.get("full_name", "")
                        for author in (article.get("authors") or {}).get("authors", [])
                        if author.get("full_name")
                    )
                    or None,
                    publication_title=_first(article.get("publication_title")),
                    publication_date=_first(article.get("publication_year")),
                    abstract=_first(article.get("abstract")),
                )
            )
        return SearchPage(
            "ieee", results, int(payload.get("total_records", len(results))), page, per_page
        )


SEARCH_ADAPTERS: dict[str, SearchAdapter] = {
    "crossref": CrossrefSearchAdapter(),
    "pubmed": PubMedSearchAdapter(),
    "pmc": PmcSearchAdapter(),
    "arxiv": ArxivSearchAdapter(),
    "openlibrary": OpenLibrarySearchAdapter(),
    "openalex": OpenAlexSearchAdapter(),
    "nasa": NasaAdsSearchAdapter(),
    "ieee": IeeeSearchAdapter(),
}


class OnlineSearchClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings or get_settings()
        agent = "Quirebase/0.1 online search"
        if self.settings.metadata_contact_email:
            agent += f" (mailto:{self.settings.metadata_contact_email})"
        self.client = httpx.Client(
            timeout=self.settings.metadata_timeout_seconds,
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": agent, "Accept": "application/json, application/atom+xml"},
        )

    def close(self) -> None:
        self.client.close()

    def _get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        try:
            with self.client.stream("GET", url, params=params, headers=headers) as response:
                if response.status_code == 404:
                    return b"{}"
                if response.status_code == 429:
                    raise MetadataLookupError("metadata search rate limit reached")
                if response.is_redirect:
                    raise MetadataLookupError("metadata search returned unexpected redirect")
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.settings.metadata_max_response_bytes:
                        raise MetadataLookupError("metadata response exceeded limit")
                return bytes(body)
        except MetadataLookupError:
            raise
        except httpx.HTTPError as error:
            raise MetadataLookupError("metadata search request failed") from error


def search_metadata(
    provider: str,
    clauses: list[SearchClause],
    *,
    page: int = 1,
    per_page: int = 10,
    sort: str = "relevance",
    year_from: int | None = None,
    year_to: int | None = None,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SearchPage:
    if provider not in SEARCH_PROVIDERS:
        raise ValueError(f"unknown search provider: {provider}")
    if not clauses or len(clauses) > 5:
        raise ValueError("one to five search clauses required")
    for clause in clauses:
        if (
            clause.field not in SEARCH_FIELDS
            or clause.operator not in SEARCH_OPERATORS
            or not clause.term.strip()
            or len(clause.term) > 300
        ):
            raise ValueError("search clause is invalid")
    page = max(1, min(page, 100))
    per_page = max(1, min(per_page, 25))
    if year_from and year_to and year_from > year_to:
        raise ValueError("starting year must not be after ending year")
    adapter = SEARCH_ADAPTERS.get(provider)
    if adapter is None:
        raise ValueError(f"unknown search provider: {provider}")
    resolved_settings = settings or get_settings()
    client = OnlineSearchClient(settings=resolved_settings, transport=transport)
    try:
        return adapter.search(
            client,
            clauses,
            page=page,
            per_page=per_page,
            sort=sort,
            year_from=year_from,
            year_to=year_to,
            settings=resolved_settings,
        )
    finally:
        client.close()
