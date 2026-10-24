from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import IO, Literal, Self

MAX_SEARCH_CLAUSES = 5
MAX_SEARCH_PAGE_SIZE = 100
MAX_LOOKUP_BATCH_SIZE = 50
type SearchSort = Literal["relevance", "published", "cited", "updated"]


@dataclass(frozen=True)
class ProviderChoice:
    id: str
    name: str
    sorts: tuple[SearchSort, ...] = ()
    identifier_namespaces: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataProviderChoices:
    search: tuple[ProviderChoice, ...]
    lookup: tuple[ProviderChoice, ...]
    max_search_page_size: int
    max_search_clauses: int = MAX_SEARCH_CLAUSES


class InquiroError(Exception):
    """Base error exposed by the Inquiro Interface."""


class InvalidProviderRequest(InquiroError, ValueError):
    """The requested provider operation is invalid."""


class CandidateNotFound(InquiroError):
    """No candidate exists for a valid upstream identifier."""


class ProviderUnavailable(InquiroError):
    """An upstream provider could not satisfy a valid request."""


class ProviderRateLimited(ProviderUnavailable):
    """An upstream rate limit, with its optional Retry-After delay."""

    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


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
class CandidateRecord:
    """Provider provenance and lookup context around a standard Commonmeta Work."""

    provider: str
    lookup_identifier: Identifier
    work: dict
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class LookupFailure:
    """A serializable failure for one input in a batch lookup."""

    code: Literal["invalid_request", "not_found", "unavailable"]
    message: str
    rate_limited: bool = False
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class LookupOutcome:
    """One lookup input and its candidate or failure, in input order."""

    value: str
    result: CandidateRecord | LookupFailure


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
