from __future__ import annotations

import json
from typing import Self
from urllib.parse import urlsplit

from inquiro.identifiers import parse_identifier
from inquiro.models import (
    AcquiredDocument,
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    DocumentRequest,
    Identifier,
    InquiroError,
    InvalidProviderRequest,
    PdfNotAvailable,
    ProviderConfig,
    ProviderRecord,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._catalog import builtin_providers
from inquiro.providers._contracts import ProviderContext, ProviderDefinition
from inquiro.transport import BoundedTransport, Exchange, HttpExchange, RemoteNotFound

SEARCH_FIELDS = frozenset({"any", "title", "author", "publication", "abstract"})
SEARCH_OPERATORS = frozenset({"and", "or", "not"})


class ProviderRuntime:
    """Deep Interface for scholarly metadata and document acquisition."""

    def __init__(self, config: ProviderConfig = ProviderConfig()) -> None:
        self._validate_config(config)
        self._initialize(config, HttpExchange(config))

    @classmethod
    def with_exchange(cls, config: ProviderConfig, exchange: Exchange) -> Self:
        runtime = cls.__new__(cls)
        runtime._initialize(config, exchange)
        return runtime

    def _initialize(self, config: ProviderConfig, exchange: Exchange) -> None:
        self._validate_config(config)

        self._config = config
        self._providers = builtin_providers()
        self._transport = BoundedTransport(config, exchange)
        self._context = ProviderContext(self._transport)
        self._closed = False

    @staticmethod
    def _validate_config(config: ProviderConfig) -> None:
        if config.timeout_seconds <= 0:
            raise InvalidProviderRequest("provider timeout must be positive")
        if config.max_response_bytes <= 0:
            raise InvalidProviderRequest("provider response limit must be positive")
        if config.max_document_bytes <= 0:
            raise InvalidProviderRequest("provider document limit must be positive")

    async def acquire_document(self, request: DocumentRequest) -> AcquiredDocument:
        self._require_open()
        source = request.source.strip()
        parsed_url = urlsplit(source)
        if "://" in source:
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise InvalidProviderRequest("PDF URL must use HTTP or HTTPS")
            try:
                identifier = parse_identifier(
                    source,
                    request.provider,
                    registrations=self._providers,
                )
            except InvalidProviderRequest:
                if request.provider != "auto":
                    raise
                return await self._transport.download_pdf(source)
        else:
            identifier = parse_identifier(
                source,
                request.provider,
                registrations=self._providers,
            )
        definition = self._identifier_provider(identifier.provider)
        if definition is None or definition.document_adapter is None:
            raise PdfNotAvailable("provider does not offer PDF acquisition")
        definition.require_credentials(self._config, "document")
        try:
            return await definition.document_adapter.acquire(
                self._context,
                identifier.value,
                self._config,
                endpoint=definition.document_endpoint or definition.endpoint,
            )
        except RemoteNotFound as error:
            raise PdfNotAvailable("PDF source was not found") from error
        except InquiroError:
            raise
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable("PDF provider returned invalid document metadata") from error

    async def lookup(self, value: str, *, provider: str = "auto") -> CandidateRecord:
        self._require_open()
        identifier = parse_identifier(value, provider, registrations=self._providers)
        definition = self._identifier_provider(identifier.provider)
        if definition is None or definition.lookup_adapter is None:
            raise InvalidProviderRequest(f"unknown identifier provider: {identifier.provider}")
        definition.require_credentials(self._config, "lookup")
        try:
            record = await definition.lookup_adapter.lookup(
                self._context,
                identifier.value,
                self._config,
                endpoint=definition.endpoint,
            )
        except RemoteNotFound as error:
            raise CandidateNotFound("metadata record was not found") from error
        except InquiroError:
            raise
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable("metadata provider returned invalid metadata") from error
        if not record.title:
            raise ProviderUnavailable("metadata provider returned a record without a title")
        return self._candidate(definition.name, identifier, record)

    async def search(self, query: SearchQuery) -> CandidatePage:
        self._require_open()
        definition = next(
            (provider for provider in self._providers if provider.name == query.provider), None
        )
        if definition is None or definition.search_adapter is None:
            raise InvalidProviderRequest(f"unknown search provider: {query.provider}")
        if not query.clauses or len(query.clauses) > 5:
            raise InvalidProviderRequest("one to five search clauses required")
        for clause in query.clauses:
            if (
                clause.field not in SEARCH_FIELDS
                or clause.operator not in SEARCH_OPERATORS
                or not clause.term.strip()
                or len(clause.term) > 300
            ):
                raise InvalidProviderRequest("search clause is invalid")
        if query.year_from and query.year_to and query.year_from > query.year_to:
            raise InvalidProviderRequest("starting year must not be after ending year")
        page = max(1, min(query.page, 100))
        per_page = max(1, min(query.per_page, 25))
        definition.require_credentials(self._config, "search")
        try:
            result = await definition.search_adapter.search(
                self._context,
                list(query.clauses),
                page=page,
                per_page=per_page,
                sort=query.sort,
                year_from=query.year_from,
                year_to=query.year_to,
                settings=self._config,
                endpoint=definition.endpoint,
            )
        except RemoteNotFound:
            return CandidatePage(definition.name, (), 0, page, per_page)
        except InquiroError:
            raise
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable(
                "metadata provider returned invalid search results"
            ) from error
        records = tuple(
            CandidateRecord(
                provider=record.provider,
                identifier=Identifier(record.identifier_provider, record.identifier),
                title=record.title,
                authors=record.authors,
                publication_title=record.publication_title,
                publication_date=record.publication_date,
                doi=record.doi,
                abstract=record.abstract,
            )
            for record in result.results
        )
        return CandidatePage(result.provider, records, result.total, page, per_page)

    async def aclose(self) -> None:
        if not self._closed:
            await self._transport.aclose()
            self._closed = True

    async def __aenter__(self) -> Self:
        self._require_open()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    def _identifier_provider(self, alias: str) -> ProviderDefinition | None:
        return next(
            (provider for provider in self._providers if alias in provider.identifier_aliases),
            None,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("provider runtime is closed")

    @staticmethod
    def _candidate(
        provider: str, identifier: Identifier, record: ProviderRecord
    ) -> CandidateRecord:
        identifiers: list[Identifier] = [identifier]
        if record.identifiers:
            try:
                raw_identifiers = json.loads(record.identifiers)
            except (json.JSONDecodeError, TypeError):
                raw_identifiers = {}
            for name, value in raw_identifiers.items():
                candidate = Identifier(str(name), str(value))
                if candidate not in identifiers:
                    identifiers.append(candidate)
        return CandidateRecord(
            provider=provider,
            identifier=identifier,
            title=record.title,
            abstract=record.abstract,
            authors=record.authors,
            keywords=record.keywords,
            publication_date=record.publication_date,
            publication_title=record.publication_title,
            journal_abbreviation=record.journal_abbreviation,
            volume=record.volume,
            issue=record.issue,
            pages=record.pages,
            publisher=record.publisher,
            affiliation=record.affiliation,
            doi=record.doi,
            urls=record.urls,
            identifiers=tuple(identifiers),
            reference_type=record.reference_type,
        )
