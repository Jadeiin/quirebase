from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import IO, Literal, Self

from inquiro.names import ContributorName
from inquiro.reference_types import ReferenceType


class InquiroError(Exception):
    """Base error exposed by the Inquiro Interface."""


class InvalidProviderRequest(InquiroError, ValueError):
    """The requested provider operation is invalid."""


class CandidateNotFound(InquiroError):
    """No candidate exists for a valid upstream identifier."""


class ProviderUnavailable(InquiroError):
    """An upstream provider could not satisfy a valid request."""


class PdfNotAvailable(InquiroError):
    """No PDF is available for a valid source."""


class PdfAccessDenied(InquiroError):
    """A PDF exists, but the configured credentials cannot access it."""


class InvalidPdfResponse(InquiroError):
    """The upstream response is not a usable PDF."""


@dataclass(frozen=True)
class ProviderConfig:
    timeout_seconds: float = 10.0
    max_response_bytes: int = 10_000_000
    max_document_bytes: int = 100_000_000
    contact_email: str | None = None
    openalex_api_key: str | None = None
    ncbi_api_key: str | None = None
    nasa_ads_token: str | None = None
    ieee_api_key: str | None = None


@dataclass(frozen=True)
class DocumentRequest:
    source: str
    provider: str = "auto"


@dataclass
class AcquiredDocument:
    stream: IO[bytes]
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    provider: str | None = None

    async def aclose(self) -> None:
        await asyncio.to_thread(self.stream.close)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def __aiter__(self):
        return self._iter_chunks()

    async def _iter_chunks(self):
        while True:
            chunk = await asyncio.to_thread(self.stream.read, 64 * 1024)
            if not chunk:
                break
            yield chunk


@dataclass(frozen=True)
class Identifier:
    """A provider-qualified lookup key or a namespaced confirmed identifier."""

    provider: str
    value: str


@dataclass(frozen=True)
class Affiliation:
    name: str
    identifiers: tuple[Identifier, ...] = ()
    country_code: str | None = None
    raw_name: str | None = None


@dataclass(frozen=True)
class Contributor:
    """One credited author, including affiliations on this particular record.

    Name parts describe upstream facts. bibliographic_name provides a separate
    formatting projection when a source supplies only a display name.
    """

    display_name: str
    family_name: str | None = None
    given_name: str | None = None
    kind: Literal["person", "organization", "unknown"] = "unknown"
    identifiers: tuple[Identifier, ...] = ()
    affiliations: tuple[Affiliation, ...] | None = None
    is_corresponding: bool | None = None
    suffix: str | None = None

    @property
    def bibliographic_name(self) -> ContributorName:
        if self.kind == "organization":
            name = ContributorName(self.display_name)
        elif self.family_name:
            name = ContributorName(self.family_name, self.given_name)
        else:
            name = ContributorName.parse(self.display_name)
        family = " ".join(part for part in (name.family_name, self.suffix) if part)
        return ContributorName(family, name.given_name)


@dataclass(frozen=True)
class ResourceLink:
    url: str
    kind: Literal["landing_page", "full_text", "other"] = "other"
    media_type: str | None = None
    version: str | None = None
    license: str | None = None
    is_open_access: bool | None = None
    intended_application: str | None = None


type JsonValue = str | int | float | bool | tuple[JsonValue, ...] | Mapping[str, JsonValue] | None


@dataclass(frozen=True)
class CustomField:
    name: str
    value: JsonValue


@dataclass(frozen=True)
class BibliographicMetadata:
    """A complete description, independent of its source and persistence."""

    title: str
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    publication_date: str | None = None
    publication_title: str | None = None
    reference_type: ReferenceType = ReferenceType.document
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    place_published: str | None = None
    journal_abbreviation: str | None = None
    citation_key: str | None = None
    urls: tuple[ResourceLink, ...] = ()
    authors: tuple[Contributor, ...] = ()
    editors: tuple[Contributor, ...] = ()
    doi: str | None = None
    identifiers: tuple[Identifier, ...] = ()
    custom_fields: tuple[CustomField, ...] = ()


@dataclass(frozen=True)
class CandidateRecord:
    """Provider metadata with a lookup key and confirmed record identities.

    provider names the metadata source. lookup_identifier preserves the parsed
    lookup input, or supplies the next lookup key for a search result.
    identifiers contains confirmed identities without injecting that lookup key.
    """

    provider: str
    lookup_identifier: Identifier
    title: str
    abstract: str | None = None
    authors: tuple[Contributor, ...] | None = None
    keywords: tuple[str, ...] | None = None
    publication_date: str | None = None
    publication_title: str | None = None
    journal_abbreviation: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    publisher: str | None = None
    urls: tuple[ResourceLink, ...] | None = None
    identifiers: tuple[Identifier, ...] = ()
    reference_type: ReferenceType | None = None

    @property
    def doi(self) -> str | None:
        return next((row.value for row in self.identifiers if row.provider == "doi"), None)


@dataclass(frozen=True)
class SearchClause:
    field: str
    operator: str
    term: str


@dataclass(frozen=True)
class SearchQuery:
    provider: str
    clauses: tuple[SearchClause, ...]
    page: int = 1
    per_page: int = 10
    sort: str = "relevance"
    year_from: int | None = None
    year_to: int | None = None


@dataclass(frozen=True)
class CandidatePage:
    provider: str
    results: tuple[CandidateRecord, ...]
    total: int
    page: int
    per_page: int
