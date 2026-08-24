from __future__ import annotations

from dataclasses import dataclass


class InquiroError(Exception):
    """Base error exposed by the Inquiro Interface."""


class InvalidProviderRequest(InquiroError, ValueError):
    """The requested provider operation is invalid."""


class CandidateNotFound(InquiroError):
    """No candidate exists for a valid upstream identifier."""


class ProviderUnavailable(InquiroError):
    """An upstream provider could not satisfy a valid request."""


@dataclass(frozen=True)
class ProviderConfig:
    timeout_seconds: float = 10.0
    max_response_bytes: int = 10_000_000
    contact_email: str | None = None
    openalex_api_key: str | None = None
    ncbi_api_key: str | None = None
    nasa_ads_token: str | None = None
    ieee_api_key: str | None = None


@dataclass(frozen=True)
class Identifier:
    provider: str
    value: str


@dataclass(frozen=True)
class CandidateRecord:
    provider: str
    identifier: Identifier
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
    identifiers: tuple[Identifier, ...] = ()
    reference_type: str | None = None


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


@dataclass(frozen=True)
class ProviderRecord:
    """Normalized provider payload before the runtime attaches its identifier."""

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


@dataclass(frozen=True)
class ProviderSearchRecord:
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
class ProviderSearchPage:
    provider: str
    results: tuple[ProviderSearchRecord, ...] | list[ProviderSearchRecord]
    total: int
    page: int
    per_page: int
