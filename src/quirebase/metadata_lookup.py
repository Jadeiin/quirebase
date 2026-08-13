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
ARXIV_PATTERN = re.compile(
    r"(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE
)
HTML_TAG = re.compile(r"<[^>]+>")
PROVIDERS = {"auto", "doi", "pmid", "arxiv"}


class MetadataLookupError(RuntimeError):
    pass


class MetadataNotFound(MetadataLookupError):
    pass


@dataclass(frozen=True)
class Identifier:
    provider: str
    value: str


def parse_identifier(value: str, provider: str = "auto") -> Identifier:
    if provider not in PROVIDERS:
        raise ValueError("provider must be auto, doi, pmid or arxiv")
    candidate = value.strip()
    if not candidate or len(candidate) > 500 or any(ord(character) < 32 for character in candidate):
        raise ValueError("identifier is invalid")
    candidate = re.sub(
        r"^https?://(?:dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE
    )
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
    if provider != "auto":
        raise ValueError(f"identifier is not a valid {provider}")
    raise ValueError("identifier is not a recognized DOI, PMID or arXiv ID")


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
    parts = (message.get("published-print") or message.get("published-online") or message.get("issued") or {}).get("date-parts", [])
    if not parts:
        return None
    return "-".join(str(number).zfill(2) if index else str(number) for index, number in enumerate(parts[0]))


class MetadataClient:
    def __init__(self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None):
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
                    raise MetadataNotFound("metadata record was not found")
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
        return self._arxiv(identifier.value)

    def _crossref(self, doi: str) -> dict[str, str | None]:
        params = {"mailto": self.settings.metadata_contact_email} if self.settings.metadata_contact_email else None
        try:
            body = self._get(f"https://api.crossref.org/works/{quote(doi, safe='')}", params)
        except MetadataNotFound:
            return self._datacite(doi)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("Crossref returned invalid metadata") from error
        message = payload.get("message", {})
        authors = "; ".join(
            ", ".join(part for part in (_first(author.get("family")), _first(author.get("given"))) if part)
            for author in message.get("author", [])
        ) or None
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
            payload = json.loads(
                self._get(f"https://api.datacite.org/dois/{quote(doi, safe='')}")
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise MetadataLookupError("DataCite returned invalid metadata") from error
        attributes = payload.get("data", {}).get("attributes", {})
        creators = attributes.get("creators", [])
        authors = "; ".join(
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
        ) or None
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
            "title": _first(
                [title.get("title") for title in attributes.get("titles", []) if title.get("title")]
            ),
            "abstract": abstract,
            "authors": authors,
            "keywords": "; ".join(
                subject.get("subject", "")
                for subject in attributes.get("subjects", [])
                if subject.get("subject")
            )
            or None,
            "publication_date": _first(attributes.get("published") or attributes.get("publicationYear")),
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
            raise MetadataNotFound("PubMed record was not found")
        identifiers = {"pmid": pmid}
        for article_id in record.get("articleids", []):
            if article_id.get("idtype") == "doi" and article_id.get("value"):
                identifiers["doi"] = article_id["value"]
        return {
            "title": _clean_markup(record.get("title")),
            "abstract": None,
            "authors": "; ".join(author["name"] for author in record.get("authors", []) if author.get("name")) or None,
            "keywords": None,
            "publication_date": _first(record.get("pubdate")),
            "publication_title": _first(record.get("fulljournalname") or record.get("source")),
            "doi": identifiers.get("doi"),
            "identifiers": json.dumps(identifiers),
            "reference_type": "journal-article",
        }

    def _arxiv(self, arxiv_id: str) -> dict[str, str | None]:
        body = self._get("https://export.arxiv.org/api/query", {"id_list": arxiv_id, "max_results": "1"})
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise MetadataLookupError("arXiv returned invalid metadata") from error
        namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        entry = root.find("atom:entry", namespace)
        if entry is None:
            raise MetadataNotFound("arXiv record was not found")
        authors = "; ".join(
            _first(node.findtext("atom:name", default="", namespaces=namespace)) or ""
            for node in entry.findall("atom:author", namespace)
        ) or None
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
            ) or None,
            "publication_date": _first(entry.findtext("atom:published", default="", namespaces=namespace)),
            "publication_title": _first(entry.findtext("arxiv:journal_ref", default="", namespaces=namespace)),
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
