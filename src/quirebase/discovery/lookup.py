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
PROVIDERS = {
    "auto",
    "doi",
    "crossref",
    "datacite",
    "pmid",
    "pubmed",
    "arxiv",
    "isbn",
    "openalex",
    "bibcode",
    "article_number",
}


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
        raise ValueError(
            "provider must be auto, doi, crossref, datacite, pmid, pubmed, arxiv, isbn, openalex, bibcode or article_number"
        )
    candidate = value.strip()
    if not candidate or len(candidate) > 500 or any(ord(character) < 32 for character in candidate):
        raise ValueError("identifier is invalid")
    candidate = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^doi:\s*", "", candidate, flags=re.IGNORECASE)
    if provider in ("auto", "doi", "crossref", "datacite") and DOI_PATTERN.fullmatch(candidate):
        target_provider = provider if provider in ("crossref", "datacite") else "doi"
        return Identifier(target_provider, candidate.rstrip(".,; "))
    pmid = re.sub(r"^pmid:\s*", "", candidate, flags=re.IGNORECASE)
    if provider in ("auto", "pmid", "pubmed") and PMID_PATTERN.fullmatch(pmid):
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
    if provider in ("auto", "openalex"):
        if OPENALEX_PATTERN.fullmatch(openalex):
            return Identifier("openalex", openalex.upper())
        if DOI_PATTERN.fullmatch(candidate):
            return Identifier("openalex", candidate.rstrip(".,; "))
    bibcode = re.sub(r"^bibcode:\s*", "", candidate, flags=re.IGNORECASE)
    if provider == "bibcode" and BIBCODE_PATTERN.fullmatch(bibcode):
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


def _reconstruct_openalex_abstract(inverted_index: Any) -> str | None:
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


CANONICAL_REFERENCE_TYPE_MAP: dict[str, str] = {
    "article": "article",
    "journal-article": "article",
    "journal_article": "article",
    "journal article": "article",
    "article-journal": "article",
    "jour": "article",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "chapter": "chapter",
    "book-chapter": "chapter",
    "book_chapter": "chapter",
    "book chapter": "chapter",
    "book-section": "chapter",
    "book_section": "chapter",
    "conference": "conference",
    "conference-paper": "conference",
    "conference_paper": "conference",
    "conference paper": "conference",
    "proceedings-article": "conference",
    "proceedings_article": "conference",
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
    return CANONICAL_REFERENCE_TYPE_MAP.get(
        cleaned, CANONICAL_REFERENCE_TYPE_MAP.get(val_str, cleaned)
    )


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

    def to_dict(self) -> dict[str, str | None]:
        return {
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "keywords": self.keywords,
            "publication_date": self.publication_date,
            "publication_title": self.publication_title,
            "journal_abbreviation": self.journal_abbreviation,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "publisher": self.publisher,
            "affiliation": self.affiliation,
            "doi": self.doi,
            "urls": self.urls,
            "identifiers": self.identifiers,
            "reference_type": self.reference_type,
        }

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key) and getattr(self, key) is not None


class LookupAdapter(Protocol):
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord: ...


class CrossrefLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
        params = (
            {"mailto": settings.metadata_contact_email} if settings.metadata_contact_email else None
        )
        body = client._get(f"https://api.crossref.org/works/{quote(value, safe='')}", params)
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

        urls = [f"https://doi.org/{canonical_doi}"]
        resource_url = _first((message.get("resource") or {}).get("primary", {}).get("URL"))
        if resource_url and resource_url not in urls:
            urls.append(resource_url)
        for link_obj in message.get("link", []):
            u = _first(link_obj.get("URL"))
            if u and u not in urls:
                urls.append(u)

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
            urls="\n".join(urls) if urls else None,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(_first(message.get("type"))),
        )


class DataCiteLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
        try:
            body = client._get(f"https://api.datacite.org/dois/{quote(value, safe='')}")
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
        urls = [f"https://doi.org/{canonical_doi}"]
        url_attr = _first(attributes.get("url"))
        if url_attr and url_attr not in urls:
            urls.append(url_attr)
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
            publication_title=_first(attributes.get("publisher")),
            volume=None,
            issue=None,
            pages=None,
            publisher=_first(attributes.get("publisher")),
            journal_abbreviation=None,
            affiliation=None,
            doi=canonical_doi,
            urls="\n".join(urls) if urls else None,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(
                resource_type.get("resourceType") or resource_type.get("resourceTypeGeneral")
            ),
        )


class PubMedLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
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
        urls = [f"https://pubmed.ncbi.nlm.nih.gov/{value}/"]
        if doi:
            identifiers["doi"] = doi
            urls.append(f"https://doi.org/{doi}")
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
            urls="\n".join(urls) if urls else None,
            identifiers=json.dumps(identifiers),
            reference_type="article",
        )


class ArxivLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
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
        urls = [f"https://arxiv.org/abs/{value}", f"https://arxiv.org/pdf/{value}.pdf"]
        if doi:
            identifiers["doi"] = doi
            urls.append(f"https://doi.org/{doi}")
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
            urls="\n".join(urls) if urls else None,
            identifiers=json.dumps(identifiers),
            reference_type="preprint",
        )


class OpenLibraryLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
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
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
        params = {"api_key": settings.openalex_api_key} if settings.openalex_api_key else None
        lookup_target = f"doi:{value}" if (value.startswith("10.") or "/" in value) else value
        try:
            body = client._get(
                f"https://api.openalex.org/works/{quote(lookup_target, safe=':')}",
                params,
            )
        except (MetadataNotFoundError, MetadataLookupError):
            if lookup_target.startswith("doi:"):
                body = client._get(
                    f"https://api.openalex.org/works/https://doi.org/{quote(value, safe='')}",
                    params,
                )
            else:
                raise
        try:
            payload = json.loads(body)
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
        biblio = payload.get("biblio") or {}
        pages = None
        if biblio.get("first_page") and biblio.get("last_page"):
            pages = f"{biblio.get('first_page')}-{biblio.get('last_page')}"
        elif biblio.get("first_page"):
            pages = str(biblio.get("first_page"))

        urls = []
        if doi:
            urls.append(f"https://doi.org/{doi}")
        landing_url = _first((payload.get("primary_location") or {}).get("landing_page_url"))
        if landing_url and landing_url not in urls:
            urls.append(landing_url)
        oa_url = _first((payload.get("open_access") or {}).get("oa_url"))
        if oa_url and oa_url not in urls:
            urls.append(oa_url)

        abstract = _reconstruct_openalex_abstract(
            payload.get("abstract_inverted_index")
        ) or _clean_markup(_first(payload.get("abstract")))
        kw_list: list[str] = []
        for topic in payload.get("topics", []):
            if (kw := _clean_markup(_first(topic.get("display_name")))) and kw not in kw_list:
                kw_list.append(kw)
        for kw_obj in payload.get("keywords", []):
            if (kw := _clean_markup(_first(kw_obj.get("display_name")))) and kw not in kw_list:
                kw_list.append(kw)
        if not kw_list:
            for concept in payload.get("concepts", []):
                if (kw := _clean_markup(_first(concept.get("display_name")))) and kw not in kw_list:
                    kw_list.append(kw)
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
            urls="\n".join(urls) if urls else None,
            identifiers=json.dumps({
                key: val for key, val in {"openalex": openalex_id, "doi": doi}.items() if val
            }),
            reference_type=normalize_reference_type(_first(payload.get("type"))),
        )


class NasaAdsLookupAdapter:
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
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
    def lookup(self, client: MetadataClient, value: str, settings: Settings) -> MetadataRecord:
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


LOOKUP_ADAPTERS: dict[str, LookupAdapter] = {
    "doi": CrossrefLookupAdapter(),
    "crossref": CrossrefLookupAdapter(),
    "datacite": DataCiteLookupAdapter(),
    "pmid": PubMedLookupAdapter(),
    "pubmed": PubMedLookupAdapter(),
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

    def lookup(self, identifier: Identifier) -> MetadataRecord:
        adapter = LOOKUP_ADAPTERS.get(identifier.provider)
        if adapter is None:
            raise ValueError(f"unknown identifier provider: {identifier.provider}")
        return adapter.lookup(self, identifier.value, self.settings)


def lookup_metadata(
    value: str,
    provider: str = "auto",
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
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
