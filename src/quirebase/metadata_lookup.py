from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

from .config import Settings, get_settings

DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
PMID_PATTERN = re.compile(r"\d{1,10}")
ISBN_PATTERN = re.compile(r"(?:97[89])?\d{9}[\dX]", re.IGNORECASE)
ARXIV_PATTERN = re.compile(
    r"(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE
)
OPENALEX_PATTERN = re.compile(r"W\d+", re.IGNORECASE)
HTML_TAG = re.compile(r"<[^>]+>")
PROVIDERS = {"auto", "doi", "pmid", "arxiv", "isbn", "openalex"}
SEARCH_PROVIDERS = {"crossref", "pubmed", "arxiv", "openlibrary", "openalex"}


class MetadataLookupError(RuntimeError):
    pass


class MetadataNotFoundError(MetadataLookupError):
    pass


@dataclass(frozen=True)
class Identifier:
    provider: str
    value: str


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
    authors: str | None
    publication_title: str | None
    publication_date: str | None
    abstract: str | None = None


@dataclass(frozen=True)
class SearchPage:
    provider: str
    results: list[SearchResult]
    total: int
    page: int
    per_page: int


def parse_identifier(value: str, provider: str = "auto") -> Identifier:
    if provider not in PROVIDERS:
        raise ValueError("provider must be auto, doi, pmid, arxiv, isbn or openalex")
    candidate = value.strip()
    if not candidate or len(candidate) > 500 or any(ord(character) < 32 for character in candidate):
        raise ValueError("identifier is invalid")
    candidate = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    if provider in ("auto", "doi") and DOI_PATTERN.fullmatch(candidate):
        return Identifier("doi", candidate.rstrip(".,; "))
    pmid = re.sub(r"^pmid:\s*", "", candidate, flags=re.IGNORECASE)
    if provider in ("auto", "pmid") and PMID_PATTERN.fullmatch(pmid):
        return Identifier("pmid", pmid)
    arxiv = re.sub(
        r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    arxiv = arxiv.removesuffix(".pdf")
    if provider in ("auto", "arxiv") and ARXIV_PATTERN.fullmatch(arxiv):
        return Identifier("arxiv", arxiv)
    isbn = re.sub(r"^(?:urn:isbn:|isbn(?:-1[03])?:?)\s*", "", candidate, flags=re.IGNORECASE)
    isbn = re.sub(r"[-\s]", "", isbn)
    if provider in ("auto", "isbn") and ISBN_PATTERN.fullmatch(isbn):
        return Identifier("isbn", isbn.upper())
    openalex = re.sub(r"^https?://openalex\.org/", "", candidate, flags=re.IGNORECASE)
    if provider in ("auto", "openalex") and OPENALEX_PATTERN.fullmatch(openalex):
        return Identifier("openalex", openalex.upper())
    if provider != "auto":
        raise ValueError(f"identifier is not a valid {provider}")
    raise ValueError("identifier is not a recognized DOI, PMID, arXiv ID, ISBN or OpenAlex ID")


def _first(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def _clean_markup(value: str | None) -> str | None:
    if not value:
        return None
    return _first(html.unescape(HTML_TAG.sub(" ", value)))


def _date_parts(message: dict) -> str | None:
    parts = (
        message.get("published-print")
        or message.get("published-online")
        or message.get("issued")
        or {}
    ).get("date-parts", [])
    if not parts:
        return None
    return "-".join(
        str(number).zfill(2) if index else str(number) for index, number in enumerate(parts[0])
    )


class MetadataClient:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or get_settings()
        agent = "Quirebase/0.1 metadata lookup"
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

    def _get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        try:
            with self.client.stream("GET", url, params=params) as response:
                if response.status_code == 404:
                    raise MetadataNotFoundError("metadata record was not found")
                if response.status_code == 429:
                    raise MetadataLookupError("metadata provider rate limit was reached")
                if response.is_redirect:
                    raise MetadataLookupError("metadata provider returned an unexpected redirect")
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > self.settings.metadata_max_response_bytes:
                        raise MetadataLookupError("metadata response exceeded the size limit")
                return bytes(body)
        except MetadataLookupError:
            raise
        except httpx.HTTPError as error:
            raise MetadataLookupError("metadata provider request failed") from error

    def lookup(self, identifier: Identifier) -> dict[str, str | None]:
        if identifier.provider == "doi":
            return self._crossref(identifier.value)
        if identifier.provider == "pmid":
            return self._pubmed(identifier.value)
        if identifier.provider == "isbn":
            return self._open_library(identifier.value)
        if identifier.provider == "openalex":
            return self._openalex(identifier.value)
        return self._arxiv(identifier.value)

    def search(
        self,
        provider: str,
        clauses: list[SearchClause],
        *,
        page: int = 1,
        per_page: int = 10,
        sort: str = "relevance",
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> SearchPage:
        if provider not in SEARCH_PROVIDERS:
            raise ValueError("unknown search provider")
        if not clauses or len(clauses) > 5:
            raise ValueError("search requires one to five clauses")
        if any(
            clause.field not in {"any", "title", "author", "publication", "abstract"}
            or clause.operator not in {"and", "or", "not"}
            or not clause.term.strip()
            or len(clause.term) > 300
            for clause in clauses
        ):
            raise ValueError("search clause is invalid")
        page = max(1, min(page, 100))
        per_page = max(1, min(per_page, 25))
        if year_from and year_to and year_from > year_to:
            raise ValueError("starting year must not be after ending year")
        if provider == "crossref":
            return self._search_crossref(clauses, page, per_page, sort, year_from, year_to)
        if provider == "pubmed":
            return self._search_pubmed(clauses, page, per_page, sort, year_from, year_to)
        if provider == "arxiv":
            return self._search_arxiv(clauses, page, per_page, sort, year_from, year_to)
        if provider == "openalex":
            return self._search_openalex(clauses, page, per_page, sort, year_from, year_to)
        return self._search_open_library(clauses, page, per_page, sort, year_from, year_to)

    def _openalex_params(self) -> dict[str, str]:
        return {"api_key": self.settings.openalex_api_key} if self.settings.openalex_api_key else {}

    @staticmethod
    def _openalex_record(record: dict) -> dict[str, str | None]:
        openalex_id = (_first(record.get("id")) or "").rsplit("/", 1)[-1]
        doi = (
            re.sub(
                r"^https?://(?:dx\.)?doi\.org/",
                "",
                _first(record.get("doi")) or "",
                flags=re.IGNORECASE,
            )
            or None
        )
        source = (record.get("primary_location") or {}).get("source") or {}
        return {
            "title": _first(record.get("display_name") or record.get("title")),
            "abstract": None,
            "authors": "; ".join(
                author_name
                for authorship in record.get("authorships", [])
                if (author_name := _first((authorship.get("author") or {}).get("display_name")))
            )
            or None,
            "keywords": "; ".join(
                keyword
                for topic in record.get("topics", [])
                if (keyword := _first(topic.get("display_name")))
            )
            or None,
            "publication_date": _first(record.get("publication_date")),
            "publication_title": _first(source.get("display_name")),
            "doi": doi,
            "identifiers": json.dumps({
                key: value for key, value in {"openalex": openalex_id, "doi": doi}.items() if value
            }),
            "reference_type": _first(record.get("type")),
        }

    def _openalex(self, openalex_id: str) -> dict[str, str | None]:
        try:
            payload = json.loads(
                self._get(
                    f"https://api.openalex.org/works/{quote(openalex_id, safe='')}",
                    self._openalex_params() or None,
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid metadata") from error
        record = self._openalex_record(payload)
        if not record["title"]:
            raise MetadataNotFoundError("OpenAlex work was not found")
        return record

    def _search_openalex(
        self,
        clauses: list[SearchClause],
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
    ) -> SearchPage:
        params = {
            **self._openalex_params(),
            "page": str(page),
            "per-page": str(per_page),
            "sort": {
                "published": "publication_date:desc",
                "cited": "cited_by_count:desc",
            }.get(sort, "relevance_score:desc"),
        }
        filters = []
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
        for field, values, negated in groups:
            if field == "publication":
                source_ids = []
                for value in values:
                    source_ids.extend(self._openalex_source_ids(value))
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
            filters.append(f"{filter_field}:{'!' if negated else ''}{filter_value}")
        if year_from:
            filters.append(f"from_publication_date:{year_from}-01-01")
        if year_to:
            filters.append(f"to_publication_date:{year_to}-12-31")
        if filters:
            params["filter"] = ",".join(filters)
        if sort == "relevance" and not any(".search:" in value for value in filters):
            params["sort"] = "cited_by_count:desc"
        try:
            payload = json.loads(self._get("https://api.openalex.org/works", params))
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid search results") from error
        results = []
        for source in payload.get("results", []):
            record = self._openalex_record(source)
            openalex_id = json.loads(record["identifiers"] or "{}").get("openalex")
            if not record["title"] or not openalex_id:
                continue
            results.append(
                SearchResult(
                    provider="openalex",
                    identifier_provider="openalex",
                    identifier=openalex_id,
                    title=record["title"],
                    authors=record["authors"],
                    publication_title=record["publication_title"],
                    publication_date=record["publication_date"],
                )
            )
        return SearchPage(
            "openalex",
            results,
            int(payload.get("meta", {}).get("count", len(results))),
            page,
            per_page,
        )

    def _openalex_source_ids(self, term: str) -> list[str]:
        try:
            payload = json.loads(
                self._get(
                    "https://api.openalex.org/sources",
                    {**self._openalex_params(), "search": term, "per-page": "10"},
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid source results") from error
        return [
            source_id
            for source in payload.get("results", [])
            if (source_id := (_first(source.get("id")) or "").rsplit("/", 1)[-1])
        ]

    def _search_crossref(
        self,
        clauses: list[SearchClause],
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
    ) -> SearchPage:
        params: dict[str, str] = {
            "rows": str(per_page),
            "offset": str((page - 1) * per_page),
            "sort": {
                "published": "published",
                "updated": "updated",
                "cited": "is-referenced-by-count",
            }.get(sort, "score"),
            "order": "desc",
        }
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
            expressions = []
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
        if self.settings.metadata_contact_email:
            params["mailto"] = self.settings.metadata_contact_email
        try:
            payload = json.loads(self._get("https://api.crossref.org/works", params))
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid search results") from error
        message = payload.get("message", {})
        results = []
        for record in message.get("items", []):
            doi = _first(record.get("DOI"))
            title = _first(record.get("title"))
            if not doi or not title:
                continue
            results.append(
                SearchResult(
                    provider="crossref",
                    identifier_provider="doi",
                    identifier=doi,
                    title=title,
                    authors="; ".join(
                        " ".join(
                            filter(
                                None, [_first(author.get("given")), _first(author.get("family"))]
                            )
                        )
                        for author in record.get("author", [])
                    )
                    or None,
                    publication_title=_first(record.get("container-title")),
                    publication_date=_date_parts(record),
                    abstract=_clean_markup(record.get("abstract")),
                )
            )
        return SearchPage(
            "crossref", results, int(message.get("total-results", len(results))), page, per_page
        )

    @staticmethod
    def _boolean_query(
        clauses: list[SearchClause], fields: dict[str, str], *, field_prefix: bool = False
    ) -> str:
        parts = []
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

    def _search_pubmed(
        self,
        clauses: list[SearchClause],
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
    ) -> SearchPage:
        query = self._boolean_query(
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
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retstart": str((page - 1) * per_page),
            "retmax": str(per_page),
            "sort": "pub date" if sort == "published" else "relevance",
            "tool": "quirebase",
        }
        if self.settings.metadata_contact_email:
            params["email"] = self.settings.metadata_contact_email
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        try:
            found = json.loads(
                self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params)
            ).get("esearchresult", {})
            identifiers = found.get("idlist", [])
            if not identifiers:
                return SearchPage("pubmed", [], int(found.get("count", 0)), page, per_page)
            summary_params = {
                "db": "pubmed",
                "id": ",".join(identifiers),
                "retmode": "json",
                "tool": "quirebase",
            }
            payload = json.loads(
                self._get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    summary_params,
                )
            ).get("result", {})
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("PubMed returned invalid search results") from error
        results = []
        for identifier in identifiers:
            record = payload.get(identifier, {})
            title = _clean_markup(record.get("title"))
            if not title:
                continue
            results.append(
                SearchResult(
                    provider="pubmed",
                    identifier_provider="pmid",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(
                        author["name"] for author in record.get("authors", []) if author.get("name")
                    )
                    or None,
                    publication_title=_first(record.get("fulljournalname") or record.get("source")),
                    publication_date=_first(record.get("pubdate")),
                )
            )
        return SearchPage("pubmed", results, int(found.get("count", len(results))), page, per_page)

    def _search_arxiv(
        self,
        clauses: list[SearchClause],
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
    ) -> SearchPage:
        fields = {
            "any": "all:",
            "title": "ti:",
            "author": "au:",
            "publication": "jr:",
            "abstract": "abs:",
        }
        query = self._boolean_query(clauses, fields, field_prefix=True)
        if year_from or year_to:
            query += (
                f" AND submittedDate:[{year_from or 1991}01010000 TO {year_to or 3000}12312359]"
            )
        body = self._get(
            "https://export.arxiv.org/api/query",
            {
                "search_query": query,
                "start": str((page - 1) * per_page),
                "max_results": str(per_page),
                "sortBy": "submittedDate" if sort == "published" else "relevance",
                "sortOrder": "descending",
            },
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise MetadataLookupError("arXiv returned invalid search results") from error
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "open": "http://a9.com/-/spec/opensearch/1.1/",
        }
        results = []
        for entry in root.findall("atom:entry", namespace):
            url = _first(entry.findtext("atom:id", namespaces=namespace)) or ""
            identifier = url.rsplit("/", 1)[-1]
            title = _first(entry.findtext("atom:title", namespaces=namespace))
            if not identifier or not title:
                continue
            results.append(
                SearchResult(
                    provider="arxiv",
                    identifier_provider="arxiv",
                    identifier=identifier,
                    title=title,
                    authors="; ".join(
                        filter(
                            None,
                            [
                                _first(author.findtext("atom:name", namespaces=namespace))
                                for author in entry.findall("atom:author", namespace)
                            ],
                        )
                    )
                    or None,
                    publication_title="arXiv",
                    publication_date=_first(entry.findtext("atom:published", namespaces=namespace)),
                    abstract=_first(entry.findtext("atom:summary", namespaces=namespace)),
                )
            )
        total = int(root.findtext("open:totalResults", default="0", namespaces=namespace))
        return SearchPage("arxiv", results, total, page, per_page)

    def _search_open_library(
        self,
        clauses: list[SearchClause],
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
    ) -> SearchPage:
        params = {
            "limit": str(per_page),
            "offset": str((page - 1) * per_page),
            "fields": "key,title,author_name,publisher,first_publish_year,isbn",
            "q": self._boolean_query(
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
        try:
            payload = json.loads(self._get("https://openlibrary.org/search.json", params))
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Open Library returned invalid search results") from error
        results = []
        for record in payload.get("docs", []):
            isbns = record.get("isbn", [])
            title = _first(record.get("title"))
            if not isbns or not title:
                continue
            results.append(
                SearchResult(
                    provider="openlibrary",
                    identifier_provider="isbn",
                    identifier=isbns[0],
                    title=title,
                    authors="; ".join(record.get("author_name", [])) or None,
                    publication_title=_first(record.get("publisher")),
                    publication_date=_first(record.get("first_publish_year")),
                )
            )
        return SearchPage(
            "openlibrary", results, int(payload.get("numFound", len(results))), page, per_page
        )

    def _open_library(self, isbn: str) -> dict[str, str | None]:
        key = f"ISBN:{isbn}"
        try:
            payload = json.loads(
                self._get(
                    "https://openlibrary.org/api/books",
                    {"bibkeys": key, "format": "json", "jscmd": "data"},
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Open Library returned invalid metadata") from error
        record = payload.get(key)
        if not record:
            raise MetadataNotFoundError("Open Library record was not found")
        return {
            "title": _first(record.get("title")),
            "abstract": None,
            "authors": "; ".join(
                author["name"] for author in record.get("authors", []) if author.get("name")
            )
            or None,
            "keywords": None,
            "publication_date": _first(record.get("publish_date")),
            "publication_title": _first([
                publisher.get("name") for publisher in record.get("publishers", [])
            ]),
            "doi": None,
            "identifiers": json.dumps({"isbn": isbn}),
            "reference_type": "book",
        }

    def _crossref(self, doi: str) -> dict[str, str | None]:
        params = (
            {"mailto": self.settings.metadata_contact_email}
            if self.settings.metadata_contact_email
            else None
        )
        try:
            body = self._get(f"https://api.crossref.org/works/{quote(doi, safe='')}", params)
        except MetadataNotFoundError:
            return self._datacite(doi)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid metadata") from error
        message = payload.get("message", {})
        authors = (
            "; ".join(
                ", ".join(
                    part
                    for part in (_first(author.get("family")), _first(author.get("given")))
                    if part
                )
                for author in message.get("author", [])
            )
            or None
        )
        return {
            "title": _first(message.get("title")),
            "abstract": _clean_markup(message.get("abstract")),
            "authors": authors,
            "keywords": "; ".join(message.get("subject", [])) or None,
            "publication_date": _date_parts(message),
            "publication_title": _first(message.get("container-title")),
            "doi": _first(message.get("DOI")) or doi,
            "identifiers": json.dumps({"doi": _first(message.get("DOI")) or doi}),
            "reference_type": _first(message.get("type")),
        }

    def _datacite(self, doi: str) -> dict[str, str | None]:
        try:
            payload = json.loads(self._get(f"https://api.datacite.org/dois/{quote(doi, safe='')}"))
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("DataCite returned invalid metadata") from error
        attributes = payload.get("data", {}).get("attributes", {})
        creators = attributes.get("creators", [])
        authors = (
            "; ".join(
                _first(creator.get("name"))
                or ", ".join(
                    part
                    for part in (
                        _first(creator.get("familyName")),
                        _first(creator.get("givenName")),
                    )
                    if part
                )
                for creator in creators
            )
            or None
        )
        abstract = next(
            (
                _clean_markup(description.get("description"))
                for description in attributes.get("descriptions", [])
                if description.get("descriptionType") == "Abstract"
            ),
            None,
        )
        resource_type = attributes.get("types", {})
        canonical_doi = _first(attributes.get("doi")) or doi
        return {
            "title": _first([
                title.get("title") for title in attributes.get("titles", []) if title.get("title")
            ]),
            "abstract": abstract,
            "authors": authors,
            "keywords": "; ".join(
                subject.get("subject", "")
                for subject in attributes.get("subjects", [])
                if subject.get("subject")
            )
            or None,
            "publication_date": _first(
                attributes.get("published") or attributes.get("publicationYear")
            ),
            "publication_title": _first(attributes.get("publisher")),
            "doi": canonical_doi,
            "identifiers": json.dumps({"doi": canonical_doi}),
            "reference_type": _first(
                resource_type.get("resourceType") or resource_type.get("resourceTypeGeneral")
            ),
        }

    def _pubmed(self, pmid: str) -> dict[str, str | None]:
        params = {"db": "pubmed", "id": pmid, "retmode": "json", "tool": "quirebase"}
        if self.settings.metadata_contact_email:
            params["email"] = self.settings.metadata_contact_email
        if self.settings.ncbi_api_key:
            params["api_key"] = self.settings.ncbi_api_key
        try:
            payload = json.loads(
                self._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params)
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("PubMed returned invalid metadata") from error
        record = payload.get("result", {}).get(pmid)
        if not record:
            raise MetadataNotFoundError("PubMed record was not found")
        identifiers = {"pmid": pmid}
        for article_id in record.get("articleids", []):
            if article_id.get("idtype") == "doi" and article_id.get("value"):
                identifiers["doi"] = article_id["value"]
        return {
            "title": _clean_markup(record.get("title")),
            "abstract": None,
            "authors": "; ".join(
                author["name"] for author in record.get("authors", []) if author.get("name")
            )
            or None,
            "keywords": None,
            "publication_date": _first(record.get("pubdate")),
            "publication_title": _first(record.get("fulljournalname") or record.get("source")),
            "doi": identifiers.get("doi"),
            "identifiers": json.dumps(identifiers),
            "reference_type": "journal-article",
        }

    def _arxiv(self, arxiv_id: str) -> dict[str, str | None]:
        body = self._get(
            "https://export.arxiv.org/api/query", {"id_list": arxiv_id, "max_results": "1"}
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise MetadataLookupError("arXiv returned invalid metadata") from error
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        entry = root.find("atom:entry", namespace)
        if entry is None:
            raise MetadataNotFoundError("arXiv record was not found")
        authors = (
            "; ".join(
                _first(node.findtext("atom:name", default="", namespaces=namespace)) or ""
                for node in entry.findall("atom:author", namespace)
            )
            or None
        )
        doi = _first(entry.findtext("arxiv:doi", default="", namespaces=namespace))
        identifiers = {"arxiv": arxiv_id}
        if doi:
            identifiers["doi"] = doi
        return {
            "title": _first(entry.findtext("atom:title", default="", namespaces=namespace)),
            "abstract": _first(entry.findtext("atom:summary", default="", namespaces=namespace)),
            "authors": authors,
            "keywords": "; ".join(
                category.get("term", "") for category in entry.findall("atom:category", namespace)
            )
            or None,
            "publication_date": _first(
                entry.findtext("atom:published", default="", namespaces=namespace)
            ),
            "publication_title": _first(
                entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)
            ),
            "doi": doi,
            "identifiers": json.dumps(identifiers),
            "reference_type": "preprint",
        }


def lookup_metadata(value: str, provider: str = "auto", **kwargs) -> tuple[Identifier, dict]:
    identifier = parse_identifier(value, provider)
    client = MetadataClient(**kwargs)
    try:
        record = client.lookup(identifier)
    finally:
        client.close()
    if not record.get("title"):
        raise MetadataLookupError("metadata provider returned a record without a title")
    return identifier, record


def search_metadata(provider: str, clauses: list[SearchClause], **kwargs) -> SearchPage:
    client_options = {key: kwargs.pop(key) for key in ("settings", "transport") if key in kwargs}
    client = MetadataClient(**client_options)
    try:
        return client.search(provider, clauses, **kwargs)
    finally:
        client.close()
