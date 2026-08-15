from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote
from xml.etree import ElementTree

import httpx

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
PROVIDERS = {"auto", "doi", "pmid", "arxiv", "isbn", "openalex", "bibcode", "article_number"}


class MetadataLookupError(RuntimeError):
    pass


class MetadataNotFoundError(MetadataLookupError):
    pass


@dataclass(frozen=True)
class Identifier:
    provider: str
    value: str


def parse_identifier(value: str, provider: str = "auto") -> Identifier:
    if provider not in PROVIDERS:
        raise ValueError("provider must be auto, doi, pmid, arxiv, isbn, openalex, bibcode or article_number")
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
    bibcode = re.sub(r"^bibcode:\s*", "", candidate, flags=re.IGNORECASE)
    if (provider == "auto" and BIBCODE_PATTERN.fullmatch(bibcode)) or (provider == "bibcode" and bibcode):
        return Identifier("bibcode", bibcode)
    article_number = re.sub(r"^(?:article_number|ieee):\s*", "", candidate, flags=re.IGNORECASE)
    if provider == "article_number" and ARTICLE_NUMBER_PATTERN.fullmatch(article_number):
        return Identifier("article_number", article_number)
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


class LookupAdapter(Protocol):
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]: ...


class CrossrefLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        params = (
            {"mailto": settings.metadata_contact_email} if settings.metadata_contact_email else None
        )
        try:
            body = client._get(f"https://api.crossref.org/works/{quote(value, safe='')}", params)
        except MetadataNotFoundError:
            return self._datacite(client, value)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid metadata") from error
        message = payload.get("message")
        if not message:
            raise MetadataNotFoundError("Crossref message was missing")
        authors = "; ".join(
            ", ".join(
                part for part in (_first(author.get("family")), _first(author.get("given"))) if part
            )
            for author in message.get("author", [])
        )
        canonical_doi = _first(message.get("DOI")) or value
        return {
            "title": _first(message.get("title")),
            "abstract": _clean_markup(message.get("abstract")),
            "authors": authors or None,
            "keywords": "; ".join(message.get("subject", [])) or None,
            "publication_date": _date_parts(message),
            "publication_title": _first(message.get("container-title")),
            "doi": canonical_doi,
            "identifiers": json.dumps({"doi": canonical_doi}),
            "reference_type": _first(message.get("type")),
        }

    def _datacite(self, client: MetadataClient, doi: str) -> dict[str, str | None]:
        try:
            body = client._get(f"https://api.datacite.org/dois/{quote(doi, safe='')}")
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
        canonical_doi = _first(attributes.get("doi")) or doi
        resource_type = attributes.get("types", {})
        return {
            "title": _clean_markup(
                _first([item.get("title") for item in attributes.get("titles", [])])
            ),
            "abstract": abstract,
            "authors": authors or None,
            "keywords": "; ".join(
                item.get("subject")
                for item in attributes.get("subjects", [])
                if item.get("subject")
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


class PubMedLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        params = {"db": "pubmed", "id": value, "retmode": "json", "tool": "quirebase"}
        if settings.metadata_contact_email:
            params["email"] = settings.metadata_contact_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        body = client._get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi", params)
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
        if doi:
            identifiers["doi"] = doi
        return {
            "title": _clean_markup(item.get("title")),
            "abstract": None,
            "authors": authors or None,
            "keywords": None,
            "publication_date": item.get("pubdate"),
            "publication_title": _first(item.get("fulljournalname") or item.get("source")),
            "doi": doi,
            "identifiers": json.dumps(identifiers),
            "reference_type": "journal-article",
        }


class ArxivLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        body = client._get(
            "https://export.arxiv.org/api/query",
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
            doi = (
                re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi_link.attrib.get("href", "")) or None
            )
        identifiers: dict[str, str] = {"arxiv": value}
        if doi:
            identifiers["doi"] = doi
        published = entry.findtext("atom:published", default="", namespaces=namespace)
        return {
            "title": _first(entry.findtext("atom:title", default="", namespaces=namespace)),
            "abstract": summary.strip() or None,
            "authors": "; ".join(
                author.findtext("atom:name", default="", namespaces=namespace).strip()
                for author in entry.findall("atom:author", namespace)
                if author.findtext("atom:name", default="", namespaces=namespace).strip()
            )
            or None,
            "keywords": "; ".join(
                category.attrib.get("term", "").strip()
                for category in entry.findall("atom:category", namespace)
                if category.attrib.get("term", "").strip()
            )
            or None,
            "publication_date": published[:10] if published else None,
            "publication_title": _first(
                entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)
            ),
            "doi": doi,
            "identifiers": json.dumps(identifiers),
            "reference_type": "preprint",
        }


class OpenLibraryLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        key = f"ISBN:{value}"
        try:
            payload = json.loads(
                client._get(
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
            "identifiers": json.dumps({"isbn": value}),
            "reference_type": "book",
        }


class OpenAlexLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        params = {"api_key": settings.openalex_api_key} if settings.openalex_api_key else None
        try:
            payload = json.loads(
                client._get(
                    f"https://api.openalex.org/works/{quote(value, safe='')}",
                    params,
                )
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("OpenAlex returned invalid metadata") from error
        openalex_id = (_first(payload.get("id")) or "").rsplit("/", 1)[-1]
        doi = (
            re.sub(
                r"^https?://(?:dx\.)?doi\.org/",
                "",
                _first(payload.get("doi")) or "",
                flags=re.IGNORECASE,
            )
            or None
        )
        source = (payload.get("primary_location") or {}).get("source") or {}
        record = {
            "title": _first(payload.get("display_name") or payload.get("title")),
            "abstract": None,
            "authors": "; ".join(
                author_name
                for authorship in payload.get("authorships", [])
                if (author_name := _first((authorship.get("author") or {}).get("display_name")))
            )
            or None,
            "keywords": "; ".join(
                keyword
                for topic in payload.get("topics", [])
                if (keyword := _first(topic.get("display_name")))
            )
            or None,
            "publication_date": _first(payload.get("publication_date")),
            "publication_title": _first(source.get("display_name")),
            "doi": doi,
            "identifiers": json.dumps({
                key: val for key, val in {"openalex": openalex_id, "doi": doi}.items() if val
            }),
            "reference_type": _first(payload.get("type")),
        }
        if not record["title"]:
            raise MetadataNotFoundError("OpenAlex work was not found")
        return record


class NasaAdsLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        if not settings.nasa_ads_token:
            raise MetadataLookupError("NASA ADS requires QUIREBASE_NASA_ADS_TOKEN")
        params = {
            "q": f'bibcode:"{value}"',
            "fl": "bibcode,title,author,doi,pubdate,pub,abstract",
            "rows": "1",
        }
        headers = {"Authorization": f"Bearer {settings.nasa_ads_token}"}
        body = client._get(
            "https://api.adsabs.harvard.edu/v1/search/query", params, headers=headers
        )
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
        return {
            "title": title,
            "abstract": _clean_markup(_first(doc.get("abstract"))),
            "authors": "; ".join(doc.get("author", [])) or None,
            "keywords": None,
            "publication_date": _first(doc.get("pubdate")),
            "publication_title": _first(doc.get("pub")),
            "doi": doi,
            "identifiers": json.dumps(identifiers),
            "reference_type": "article",
        }


class IeeeLookupAdapter:
    def lookup(
        self, client: MetadataClient, value: str, settings: Settings
    ) -> dict[str, str | None]:
        if not settings.ieee_api_key:
            raise MetadataLookupError("IEEE Xplore requires QUIREBASE_IEEE_API_KEY")
        params = {
            "apikey": settings.ieee_api_key,
            "format": "json",
            "article_number": value,
        }
        body = client._get("https://ieeexploreapi.ieee.org/api/v1/search/articles", params)
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
        return {
            "title": title,
            "abstract": _clean_markup(_first(article.get("abstract"))),
            "authors": authors or None,
            "keywords": None,
            "publication_date": _first(article.get("publication_year")),
            "publication_title": _first(article.get("publication_title")),
            "doi": doi,
            "identifiers": json.dumps(identifiers),
            "reference_type": "article",
        }


LOOKUP_ADAPTERS: dict[str, LookupAdapter] = {
    "doi": CrossrefLookupAdapter(),
    "pmid": PubMedLookupAdapter(),
    "arxiv": ArxivLookupAdapter(),
    "isbn": OpenLibraryLookupAdapter(),
    "openalex": OpenAlexLookupAdapter(),
    "bibcode": NasaAdsLookupAdapter(),
    "article_number": IeeeLookupAdapter(),
}


class MetadataClient:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.BaseTransport | None = None,
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
        except httpx.HTTPError as error:
            raise MetadataLookupError("metadata provider request failed") from error

    def lookup(self, identifier: Identifier) -> dict[str, str | None]:
        adapter = LOOKUP_ADAPTERS.get(identifier.provider)
        if adapter is None:
            raise ValueError(f"unknown identifier provider: {identifier.provider}")
        return adapter.lookup(self, identifier.value, self.settings)


def lookup_metadata(
    value: str,
    provider: str = "auto",
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[Identifier, dict[str, str | None]]:
    identifier = parse_identifier(value, provider)
    client = MetadataClient(settings=settings, transport=transport)
    try:
        record = client.lookup(identifier)
    finally:
        client.close()
    if not record.get("title"):
        raise MetadataLookupError("metadata provider returned a record without a title")
    return identifier, record
