from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Protocol, cast
from urllib.parse import quote
from xml.etree import ElementTree

import httpx2

from quirebase.core.config import Settings, get_settings

DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
PMID_PATTERN = re.compile(r"\d{1,10}")
ISBN_PATTERN = re.compile(r"(?:97[89])?\d{9}[\dX]", re.IGNORECASE)
ARXIV_PATTERN = re.compile(
    r"(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE
)
OPENALEX_PATTERN = re.compile(r"W\d+", re.IGNORECASE)
BIBCODE_PATTERN = re.compile(r"\d{4}[A-Za-z0-9.&]{5,20}")
ARTICLE_NUMBER_PATTERN = re.compile(r"\d{1,12}")
HTML_TAG = re.compile(r"<[^>]+>")


class MetadataLookupError(RuntimeError):
    pass


class MetadataNotFoundError(MetadataLookupError):
    pass


@dataclass(frozen=True)
class Identifier:
    provider: str
    value: str


def normalize_doi(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"^doi:\s*", "", cleaned, flags=re.IGNORECASE)


def _parse_doi_identifier(candidate: str, alias: str) -> Identifier | None:
    if not DOI_PATTERN.fullmatch(candidate):
        return None
    provider = alias if alias in ("crossref", "datacite") else "doi"
    return Identifier(provider, candidate.rstrip(".,; "))


def _parse_pmid_identifier(candidate: str, _alias: str) -> Identifier | None:
    pmid = re.sub(r"^pmid:\s*", "", candidate, flags=re.IGNORECASE)
    if PMID_PATTERN.fullmatch(pmid):
        return Identifier("pmid", pmid)
    return None


def _parse_arxiv_identifier(candidate: str, _alias: str) -> Identifier | None:
    arxiv = re.sub(
        r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)",
        "",
        candidate,
        flags=re.IGNORECASE,
    )
    arxiv = arxiv.removesuffix(".pdf")
    if ARXIV_PATTERN.fullmatch(arxiv):
        return Identifier("arxiv", arxiv)
    return None


def _parse_isbn_identifier(candidate: str, _alias: str) -> Identifier | None:
    isbn = re.sub(r"^(?:urn:isbn:|isbn(?:-1[03])?:?)\s*", "", candidate, flags=re.IGNORECASE)
    isbn = re.sub(r"[-\s]", "", isbn)
    if ISBN_PATTERN.fullmatch(isbn):
        return Identifier("isbn", isbn.upper())
    return None


def _parse_openalex_identifier(candidate: str, _alias: str) -> Identifier | None:
    openalex = re.sub(r"^https?://openalex\.org/", "", candidate, flags=re.IGNORECASE)
    if OPENALEX_PATTERN.fullmatch(openalex):
        return Identifier("openalex", openalex.upper())
    if DOI_PATTERN.fullmatch(candidate):
        return Identifier("openalex", candidate.rstrip(".,; "))
    return None


def _parse_bibcode_identifier(candidate: str, _alias: str) -> Identifier | None:
    bibcode = re.sub(r"^bibcode:\s*", "", candidate, flags=re.IGNORECASE)
    if BIBCODE_PATTERN.fullmatch(bibcode):
        return Identifier("bibcode", bibcode)
    return None


def _parse_ieee_identifier(candidate: str, _alias: str) -> Identifier | None:
    article_number = re.sub(r"^(?:article_number|ieee):\s*", "", candidate, flags=re.IGNORECASE)
    if ARTICLE_NUMBER_PATTERN.fullmatch(article_number):
        return Identifier("article_number", article_number)
    return None


def parse_identifier(value: str, provider: str = "auto") -> Identifier:
    from quirebase.discovery.providers import (
        identifier_provider,
        identifier_provider_names,
        provider_registrations,
    )

    provider_names = identifier_provider_names()
    if provider != "auto" and provider not in provider_names:
        raise ValueError(
            f"provider must be auto, {', '.join(provider_names[:-1])} or {provider_names[-1]}"
        )
    candidate = normalize_doi(value)
    if not candidate or len(candidate) > 500 or any(ord(character) < 32 for character in candidate):
        raise ValueError("identifier is invalid")
    if provider == "auto":
        for registration in provider_registrations():
            if not registration.auto_detect_identifier or registration.identifier_parser is None:
                continue
            identifier = registration.identifier_parser(candidate, provider)
            if identifier is not None:
                return identifier
    else:
        selected_registration = identifier_provider(provider)
        if (
            selected_registration is not None
            and selected_registration.identifier_parser is not None
        ):
            identifier = selected_registration.identifier_parser(candidate, provider)
            if identifier is not None:
                return identifier
    if provider != "auto":
        raise ValueError(f"identifier is not a valid {provider}")
    raise ValueError("identifier is not a recognized DOI, PMID, arXiv ID, ISBN or OpenAlex ID")


def _collect_urls(*candidates: Any) -> str | None:
    urls: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in urls:
            urls.append(candidate)
    return "\n".join(urls) if urls else None


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


def reconstruct_openalex_abstract(inverted_index: Any) -> str | None:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            word_positions.extend((pos, word) for pos in positions if isinstance(pos, int))
    if not word_positions:
        return None
    word_positions.sort(key=lambda item: item[0])
    return _clean_markup(" ".join(word for _, word in word_positions))


def _collect_openalex_keyword_names(*collections: Any) -> list[str]:
    names: list[str] = []
    for entries in collections:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = _clean_markup(_first(entry.get("display_name")))
            if name and name not in names:
                names.append(name)
    return names


# Keyed on dash-form lower-case aliases only; normalize_reference_type replaces
# "_" and spaces with "-" before lookup, so variant forms need no entries here.
CANONICAL_REFERENCE_TYPE_MAP: dict[str, str] = {
    "article": "article",
    "journal-article": "article",
    "article-journal": "article",
    "jour": "article",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "chapter": "chapter",
    "book-chapter": "chapter",
    "book-section": "chapter",
    "conference": "conference",
    "conference-paper": "conference",
    "proceedings-article": "conference",
    "proceedings": "conference",
    "paper-conference": "conference",
    "preprint": "preprint",
    "posted-content": "preprint",
    "working-paper": "preprint",
    "thesis": "thesis",
    "dissertation": "thesis",
    "phdthesis": "thesis",
    "mastersthesis": "thesis",
    "report": "report",
    "techreport": "report",
    "dataset": "dataset",
    "patent": "patent",
    "standard": "standard",
    "generic": "generic",
    "misc": "generic",
    "other": "generic",
    "unpublished": "generic",
}


def normalize_reference_type(value: Any) -> str | None:
    if not value:
        return None
    val_str = str(value).strip().lower()
    cleaned = val_str.replace("_", "-").replace(" ", "-")
    return CANONICAL_REFERENCE_TYPE_MAP.get(cleaned, cleaned)


@dataclass
class MetadataRecord:
    title: str
    abstract: str | None = None
    authors: str | None = None
    keywords: str | None = None
    publication_date: str | None = None
    publication_title: str | None = None
    journal_abbreviation: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    affiliation: str | None = None
    doi: str | None = None
    urls: str | None = None
    identifiers: str | None = None
    reference_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LookupAdapter(Protocol):
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord: ...


class CrossrefLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        params = (
            {"mailto": settings.metadata_contact_email} if settings.metadata_contact_email else None
        )
        body = client._get(f"{endpoint}/{quote(value, safe='')}", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid metadata") from error
        message = payload.get("message")
        if not message:
            raise MetadataNotFoundError("Crossref message was missing")
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
        )
        canonical_doi = _first(message.get("DOI")) or value

        affiliations = []
        for author in message.get("author", []):
            for aff in author.get("affiliation", []):
                name = _clean_markup(_first(aff.get("name")))
                if name and name not in affiliations:
                    affiliations.append(name)
        affiliation_str = "; ".join(affiliations) if affiliations else None

        short_titles = message.get("short-container-title", [])
        journal_abbr = _clean_markup(_first(short_titles)) if short_titles else None

        urls = _collect_urls(
            f"https://doi.org/{canonical_doi}",
            _first((message.get("resource") or {}).get("primary", {}).get("URL")),
            *(_first(link.get("URL")) for link in message.get("link", [])),
        )

        abstract_val = _clean_markup(message.get("abstract"))
        keywords_val = (
            "; ".join(kw for s in message.get("subject", []) if (kw := _clean_markup(s))) or None
        )

        return MetadataRecord(
            title=_clean_markup(_first(message.get("title"))) or "",
            abstract=abstract_val,
            authors=authors or None,
            keywords=keywords_val,
            publication_date=_date_parts(message),
            publication_title=_clean_markup(_first(message.get("container-title"))),
            journal_abbreviation=journal_abbr,
            volume=_first(message.get("volume")),
            issue=_first(message.get("issue") or (message.get("journal-issue") or {}).get("issue")),
            pages=_first(message.get("page")),
            publisher=_clean_markup(_first(message.get("publisher"))),
            affiliation=affiliation_str,
            doi=canonical_doi,
            urls=urls,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(_first(message.get("type"))),
        )


class DataCiteLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        try:
            body = client._get(f"{endpoint}/{quote(value, safe='')}")
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("DataCite returned invalid metadata") from error
        attributes = (payload.get("data") or {}).get("attributes") or {}
        if not attributes:
            raise MetadataNotFoundError("DataCite record was missing")
        authors = "; ".join(
            author.get("name") for author in attributes.get("creators", []) if author.get("name")
        )
        abstract = next(
            (
                _clean_markup(item.get("description"))
                for item in attributes.get("descriptions", [])
                if item.get("descriptionType") == "Abstract"
            ),
            None,
        )
        canonical_doi = _first(attributes.get("doi")) or value
        resource_type = attributes.get("types", {})
        publisher = _first(attributes.get("publisher"))
        urls = _collect_urls(f"https://doi.org/{canonical_doi}", _first(attributes.get("url")))
        keywords = (
            "; ".join(
                item.get("subject")
                for item in attributes.get("subjects", [])
                if item.get("subject")
            )
            or None
        )
        return MetadataRecord(
            title=_clean_markup(
                _first([item.get("title") for item in attributes.get("titles", [])])
            )
            or "",
            abstract=abstract,
            authors=authors or None,
            keywords=keywords,
            publication_date=_first(
                attributes.get("published") or attributes.get("publicationYear")
            ),
            publication_title=publisher,
            publisher=publisher,
            doi=canonical_doi,
            urls=urls,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(
                resource_type.get("resourceType") or resource_type.get("resourceTypeGeneral")
            ),
        )


class PubMedLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        params = {"db": "pubmed", "id": value, "retmode": "json", "tool": "quirebase"}
        if settings.metadata_contact_email:
            params["email"] = settings.metadata_contact_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        body = client._get(f"{endpoint}/esummary.fcgi", params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("PubMed returned invalid metadata") from error
        result = payload.get("result", {})
        item = result.get(value)
        if not item or not item.get("title"):
            raise MetadataNotFoundError("PubMed article was not found")
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
        return MetadataRecord(
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


class ArxivLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        body = client._get(
            endpoint,
            {"id_list": value, "max_results": "1"},
        )
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise MetadataLookupError("arXiv returned invalid XML") from error
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }
        entry = root.find("atom:entry", namespace)
        if entry is None or entry.find("atom:title", namespace) is None:
            raise MetadataNotFoundError("arXiv entry was not found")
        summary = entry.findtext("atom:summary", default="", namespaces=namespace)
        if summary.strip().lower().startswith("error:"):
            raise MetadataNotFoundError("arXiv returned an error entry")
        doi = entry.findtext("arxiv:doi", default="", namespaces=namespace) or None
        doi_link = entry.find("atom:link[@title='doi']", namespace)
        if not doi and doi_link is not None:
            doi = normalize_doi(doi_link.attrib.get("href", "")) or None
        identifiers: dict[str, str] = {"arxiv": value}
        urls = _collect_urls(
            f"https://arxiv.org/abs/{value}",
            f"https://arxiv.org/pdf/{value}.pdf",
            f"https://doi.org/{doi}" if doi else None,
        )
        if doi:
            identifiers["doi"] = doi
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        return MetadataRecord(
            title=_first(entry.findtext("atom:title", default="", namespaces=namespace)) or "",
            abstract=summary.strip() or None,
            authors="; ".join(
                author.findtext("atom:name", default="", namespaces=namespace).strip()
                for author in entry.findall("atom:author", namespace)
                if author.findtext("atom:name", default="", namespaces=namespace).strip()
            )
            or None,
            keywords="; ".join(
                category.attrib.get("term", "").strip()
                for category in entry.findall("atom:category", namespace)
                if category.attrib.get("term", "").strip()
            )
            or None,
            publication_date=published[:10] if published else None,
            publication_title=_first(
                entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)
            ),
            doi=doi,
            urls=urls,
            identifiers=json.dumps(identifiers),
            reference_type="preprint",
        )


class OpenLibraryLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        key = f"ISBN:{value}"
        try:
            payload = json.loads(
                client._get(
                    f"{endpoint}/api/books",
                    {"bibkeys": key, "format": "json", "jscmd": "data"},
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Open Library returned invalid metadata") from error
        record = payload.get(key)
        if not record:
            raise MetadataNotFoundError("Open Library record was not found")
        return MetadataRecord(
            title=_first(record.get("title")) or "",
            abstract=None,
            authors="; ".join(
                author["name"] for author in record.get("authors", []) if author.get("name")
            )
            or None,
            keywords=None,
            publication_date=_first(record.get("publish_date")),
            publication_title=_first([
                publisher.get("name") for publisher in record.get("publishers", [])
            ]),
            doi=None,
            urls=f"https://openlibrary.org/isbn/{value}",
            identifiers=json.dumps({"isbn": value}),
            reference_type="book",
        )


class OpenAlexLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        params = {"api_key": settings.openalex_api_key} if settings.openalex_api_key else None
        lookup_target = f"doi:{value}" if DOI_PATTERN.fullmatch(value) else value
        try:
            body = client._get(
                f"{endpoint}/works/{quote(lookup_target, safe=':')}",
                params,
            )
        except (MetadataNotFoundError, MetadataLookupError):
            if lookup_target.startswith("doi:"):
                body = client._get(
                    f"{endpoint}/works/https://doi.org/{quote(value, safe='')}",
                    params,
                )
            else:
                raise
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid metadata") from error
        openalex_id = (_first(payload.get("id")) or "").rsplit("/", 1)[-1]
        doi = normalize_doi(_first(payload.get("doi")) or "") or None
        source = (payload.get("primary_location") or {}).get("source") or {}
        biblio = payload.get("biblio") or {}
        pages = None
        if biblio.get("first_page") and biblio.get("last_page"):
            pages = f"{biblio.get('first_page')}-{biblio.get('last_page')}"
        elif biblio.get("first_page"):
            pages = str(biblio.get("first_page"))

        urls = _collect_urls(
            f"https://doi.org/{doi}" if doi else None,
            _first((payload.get("primary_location") or {}).get("landing_page_url")),
            _first((payload.get("open_access") or {}).get("oa_url")),
        )

        abstract = reconstruct_openalex_abstract(
            payload.get("abstract_inverted_index")
        ) or _clean_markup(_first(payload.get("abstract")))
        kw_list = _collect_openalex_keyword_names(payload.get("topics"), payload.get("keywords"))
        if not kw_list:
            kw_list = _collect_openalex_keyword_names(payload.get("concepts"))
        keywords_val = "; ".join(kw_list) if kw_list else None
        title = _clean_markup(_first(payload.get("display_name") or payload.get("title"))) or ""

        return MetadataRecord(
            title=title,
            abstract=abstract,
            authors="; ".join(
                author_name
                for authorship in payload.get("authorships", [])
                if (author_name := _first((authorship.get("author") or {}).get("display_name")))
            )
            or None,
            keywords=keywords_val,
            publication_date=_first(payload.get("publication_date")),
            publication_title=_first(source.get("display_name")),
            volume=_first(biblio.get("volume")),
            issue=_first(biblio.get("issue")),
            pages=pages,
            publisher=_first(source.get("host_organization_name")),
            doi=doi,
            urls=urls,
            identifiers=json.dumps({
                key: val for key, val in {"openalex": openalex_id, "doi": doi}.items() if val
            }),
            reference_type=normalize_reference_type(_first(payload.get("type"))),
        )


class NasaAdsLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        token = cast("str", settings.nasa_ads_token)
        params = {
            "q": f'bibcode:"{value}"',
            "fl": "bibcode,title,author,doi,pubdate,pub,abstract",
            "rows": "1",
        }
        headers = {"Authorization": f"Bearer {token}"}
        body = client._get(endpoint, params, headers=headers)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("NASA ADS returned invalid metadata") from error
        docs = (payload.get("response") or {}).get("docs", [])
        if not docs:
            raise MetadataNotFoundError("NASA ADS record was not found")
        doc = docs[0]
        title = _clean_markup(_first(doc.get("title")))
        if not title:
            raise MetadataNotFoundError("NASA ADS record was not found")
        doi = _first(doc.get("doi"))
        bibcode = _first(doc.get("bibcode")) or value
        identifiers = {"bibcode": bibcode}
        if doi:
            identifiers["doi"] = doi
        return MetadataRecord(
            title=title,
            abstract=_clean_markup(_first(doc.get("abstract"))),
            authors="; ".join(doc.get("author", [])) or None,
            keywords=None,
            publication_date=_first(doc.get("pubdate")),
            publication_title=_first(doc.get("pub")),
            doi=doi,
            urls=f"https://ui.adsabs.harvard.edu/abs/{value}/abstract",
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class IeeeLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings, *, endpoint: str
    ) -> MetadataRecord:
        api_key = cast("str", settings.ieee_api_key)
        params = {
            "apikey": api_key,
            "format": "json",
            "article_number": value,
        }
        body = client._get(endpoint, params)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("IEEE Xplore returned invalid metadata") from error
        articles = payload.get("articles", [])
        if not articles:
            raise MetadataNotFoundError("IEEE Xplore article was not found")
        article = articles[0]
        title = _clean_markup(_first(article.get("title")))
        if not title:
            raise MetadataNotFoundError("IEEE Xplore article was not found")
        doi = _first(article.get("doi"))
        article_number = _first(article.get("article_number")) or value
        identifiers = {"article_number": article_number}
        if doi:
            identifiers["doi"] = doi
        authors = "; ".join(
            author.get("full_name", "")
            for author in (article.get("authors") or {}).get("authors", [])
            if author.get("full_name")
        )
        return MetadataRecord(
            title=title,
            abstract=_clean_markup(_first(article.get("abstract"))),
            authors=authors or None,
            keywords=None,
            publication_date=_first(article.get("publication_year")),
            publication_title=_first(article.get("publication_title")),
            doi=doi,
            urls=f"https://ieeexplore.ieee.org/document/{value}",
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class MetadataClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx2.BaseTransport | None = None,
    ):
        self.settings = settings or get_settings()
        agent = "Quirebase/0.1 metadata lookup"
        if self.settings.metadata_contact_email:
            agent += f" (mailto:{self.settings.metadata_contact_email})"
        self.client = httpx2.Client(
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
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        try:
            with self.client.stream("GET", url, params=params, headers=headers) as response:
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
        except httpx2.HTTPError as error:
            raise MetadataLookupError("metadata provider request failed") from error

    def lookup(self, identifier: Identifier) -> MetadataRecord:
        from quirebase.discovery.providers import identifier_provider

        registration = identifier_provider(identifier.provider)
        if registration is None or registration.lookup_adapter is None:
            raise ValueError(f"unknown identifier provider: {identifier.provider}")
        registration.require_credentials(self.settings)
        adapter = cast("LookupAdapter", registration.lookup_adapter)
        return adapter.lookup(
            self,
            identifier.value,
            self.settings,
            endpoint=registration.endpoint,
        )


def lookup_metadata(
    value: str,
    provider: str = "auto",
    settings: Settings | None = None,
    transport: httpx2.BaseTransport | None = None,
) -> tuple[Identifier, MetadataRecord]:
    identifier = parse_identifier(value, provider)
    client = MetadataClient(settings=settings, transport=transport)
    try:
        record = client.lookup(identifier)
    finally:
        client.close()
    if not record.title:
        raise MetadataLookupError("metadata provider returned a record without a title")
    return identifier, record
