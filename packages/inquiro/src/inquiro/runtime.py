from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime
from typing import TYPE_CHECKING, Self
from urllib.parse import urlsplit

from inquiro.canonical import normalize_publication_date
from inquiro.identifiers import parse_identifier
from inquiro.models import (
    MAX_LOOKUP_BATCH_SIZE,
    MAX_SEARCH_CLAUSES,
    MAX_SEARCH_PAGE_SIZE,
    SEARCH_FIELDS,
    SEARCH_OPERATORS,
    AcquiredDocument,
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    DocumentRequest,
    Identifier,
    InquiroError,
    InvalidProviderRequest,
    LookupFailure,
    LookupOutcome,
    MetadataProviderChoices,
    PdfNotAvailable,
    ProviderChoice,
    ProviderConfig,
    ProviderRateLimited,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._catalog import builtin_providers
from inquiro.transport import (
    BoundedTransport,
    Exchange,
    HttpExchange,
    MetadataResponseTooLarge,
    RemoteNotFound,
)
from inquiro.work import InvalidWork, validate_work

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.providers._contracts import ProviderDefinition


def _lookup_failure(
    error: InvalidProviderRequest | CandidateNotFound | ProviderUnavailable,
) -> LookupFailure:
    if isinstance(error, InvalidProviderRequest):
        return LookupFailure("invalid_request", str(error))
    if isinstance(error, CandidateNotFound):
        return LookupFailure("not_found", str(error))
    if isinstance(error, ProviderRateLimited):
        return LookupFailure("unavailable", str(error), True, error.retry_after_seconds)
    return LookupFailure("unavailable", str(error))


def _normalize_candidate(record: CandidateRecord) -> CandidateRecord:
    try:
        work = validate_work(record.work)
        # The schema's date regex accepts invalid calendar components. Check them
        # before retaining the supplied precision, including complete timestamps.
        if published := work.get("date_published"):
            if "T" in published:
                datetime.fromisoformat(published)
            else:
                parts = [int(part) for part in published.split("-")]
                date(*(parts + [1] * (3 - len(parts))))
        return replace(record, work=work)
    except (InvalidWork, ValueError):
        pass
    work = dict(record.work)
    if "date_published" in work:
        normalized = normalize_publication_date(work["date_published"])
        if normalized:
            work["date_published"] = normalized
        else:
            work.pop("date_published")
    try:
        return replace(record, work=validate_work(work))
    except InvalidWork as error:
        raise ProviderUnavailable(f"provider returned invalid Commonmeta: {error}") from error


def metadata_provider_choices(config: ProviderConfig = ProviderConfig()) -> MetadataProviderChoices:
    """Describe configured metadata capabilities without exposing the private catalog."""
    return MetadataProviderChoices(
        search=tuple(
            ProviderChoice(
                provider.name, provider.display_name or provider.name, provider.search_sorts
            )
            for provider in builtin_providers()
            if provider.search_adapter is not None and provider.has_credentials(config, "search")
        ),
        lookup=tuple(
            ProviderChoice(
                provider.name,
                provider.display_name or provider.name,
                identifier_namespaces=(
                    provider.identifier_namespace,
                    *provider.additional_lookup_namespaces,
                ),
            )
            for provider in builtin_providers()
            if (provider.lookup_adapter is not None or provider.batch_lookup_adapter is not None)
            and provider.has_credentials(config, "lookup")
        ),
        max_search_page_size=MAX_SEARCH_PAGE_SIZE,
    )


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
                self._transport,
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
        identifier, definition = self._resolve_lookup(value, provider)
        return await self._lookup(identifier, definition)

    def _resolve_lookup(self, value: str, provider: str) -> tuple[Identifier, ProviderDefinition]:
        identifier = parse_identifier(value, provider, registrations=self._providers)
        definition = self._identifier_provider(identifier.provider)
        if definition is None or (
            definition.lookup_adapter is None and definition.batch_lookup_adapter is None
        ):
            raise InvalidProviderRequest(f"unknown identifier provider: {identifier.provider}")
        definition.require_credentials(self._config, "lookup")
        return identifier, definition

    async def _lookup(
        self, identifier: Identifier, definition: ProviderDefinition
    ) -> CandidateRecord:
        try:
            if definition.batch_lookup_adapter is not None:
                results = await definition.batch_lookup_adapter.lookup_many(
                    self._transport, (identifier,), self._config, endpoint=definition.endpoint
                )
                if len(results) != 1:
                    raise ProviderUnavailable("metadata provider returned an incomplete batch")
                record = results[0]
                if isinstance(record, LookupFailure):
                    if record.code == "invalid_request":
                        raise InvalidProviderRequest(record.message)
                    if record.code == "not_found":
                        raise CandidateNotFound(record.message)
                    if record.rate_limited:
                        raise ProviderRateLimited(record.message, record.retry_after_seconds)
                    raise ProviderUnavailable(record.message)
            elif definition.lookup_adapter is not None:
                record = await definition.lookup_adapter.lookup(
                    self._transport, identifier, self._config, endpoint=definition.endpoint
                )
            else:
                raise InvalidProviderRequest(f"unknown identifier provider: {identifier.provider}")
        except RemoteNotFound as error:
            raise CandidateNotFound("metadata record was not found") from error
        except InquiroError:
            raise
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable("metadata provider returned invalid metadata") from error
        return _normalize_candidate(record)

    async def lookup_many(
        self, values: Sequence[str], *, provider: str = "auto"
    ) -> tuple[LookupOutcome, ...]:
        """Resolve up to 50 inputs, retaining order and failures with bounded Provider I/O."""
        self._require_open()
        if (
            isinstance(values, (str, bytes))
            or not 1 <= len(values) <= MAX_LOOKUP_BATCH_SIZE
            or any(not isinstance(value, str) for value in values)
        ):
            raise InvalidProviderRequest(
                f"lookup requires 1 to {MAX_LOOKUP_BATCH_SIZE} identifier strings"
            )
        values = tuple(values)
        outcomes: dict[int, LookupOutcome] = {}
        groups: dict[str, list[tuple[int, str, Identifier]]] = {}
        definitions: dict[str, ProviderDefinition] = {}
        for index, value in enumerate(values):
            try:
                identifier, definition = self._resolve_lookup(value, provider)
            except (InvalidProviderRequest, CandidateNotFound, ProviderUnavailable) as error:
                outcomes[index] = LookupOutcome(value, _lookup_failure(error))
                continue
            groups.setdefault(definition.name, []).append((index, value, identifier))
            definitions[definition.name] = definition

        semaphore = asyncio.Semaphore(3)

        async def single(entry: tuple[int, str, Identifier], definition: ProviderDefinition):
            index, value, identifier = entry
            async with semaphore:
                try:
                    result: CandidateRecord | LookupFailure = await self._lookup(
                        identifier, definition
                    )
                except (InvalidProviderRequest, CandidateNotFound, ProviderUnavailable) as error:
                    result = _lookup_failure(error)
            outcomes[index] = LookupOutcome(value, result)

        async def batch(entries: list[tuple[int, str, Identifier]], definition: ProviderDefinition):
            adapter = definition.batch_lookup_adapter
            if adapter is None:
                for entry in entries:
                    await single(entry, definition)
                return
            try:
                async with semaphore:
                    results = await adapter.lookup_many(
                        self._transport,
                        tuple(entry[2] for entry in entries),
                        self._config,
                        endpoint=definition.endpoint,
                    )
                if len(results) != len(entries):
                    raise ProviderUnavailable("metadata provider returned an incomplete batch")
            except MetadataResponseTooLarge as error:
                keys = tuple(dict.fromkeys(entry[2] for entry in entries))
                if len(keys) > 1:
                    # Keep every position for one key together so each child
                    # request shrinks after the adapter deduplicates its keys.
                    first_half = set(keys[: len(keys) // 2])
                    await batch([entry for entry in entries if entry[2] in first_half], definition)
                    await batch(
                        [entry for entry in entries if entry[2] not in first_half], definition
                    )
                    return
                results = (_lookup_failure(error),) * len(entries)
            except RemoteNotFound:
                results = (
                    LookupFailure("unavailable", "metadata batch endpoint was not found"),
                ) * len(entries)
            except (InvalidProviderRequest, CandidateNotFound, ProviderUnavailable) as error:
                results = (_lookup_failure(error),) * len(entries)
            except (TypeError, ValueError):
                results = (
                    LookupFailure("unavailable", "metadata provider returned invalid metadata"),
                ) * len(entries)
            for (index, value, _identifier), result in zip(entries, results, strict=True):
                if isinstance(result, CandidateRecord):
                    try:
                        result = _normalize_candidate(result)
                    except ProviderUnavailable as error:
                        result = _lookup_failure(error)
                outcomes[index] = LookupOutcome(value, result)

        # Join all work before the caller can close the shared transport, including on cancellation.
        async with asyncio.TaskGroup() as tasks:
            for name, entries in groups.items():
                definition = definitions[name]
                if definition.batch_lookup_adapter is not None:
                    tasks.create_task(batch(entries, definition))
                else:
                    for entry in entries:
                        tasks.create_task(single(entry, definition))
        return tuple(outcomes[index] for index in range(len(values)))

    async def search(self, query: SearchQuery) -> CandidatePage:
        self._require_open()
        definition = next(
            (provider for provider in self._providers if provider.name == query.provider), None
        )
        if definition is None or definition.search_adapter is None:
            raise InvalidProviderRequest(f"unknown search provider: {query.provider}")
        if query.sort not in definition.search_sorts:
            raise InvalidProviderRequest("sort is not supported by this search provider")
        if not query.clauses or len(query.clauses) > MAX_SEARCH_CLAUSES:
            raise InvalidProviderRequest(f"one to {MAX_SEARCH_CLAUSES} search clauses required")
        for clause in query.clauses:
            if clause.field not in SEARCH_FIELDS:
                raise InvalidProviderRequest(f"unknown search field: {clause.field}")
            if clause.operator not in SEARCH_OPERATORS:
                raise InvalidProviderRequest(f"unknown search operator: {clause.operator}")
            if not clause.term.strip():
                raise InvalidProviderRequest("search term is required")
            if len(clause.term) > 300:
                raise InvalidProviderRequest("search term is limited to 300 characters")
        if query.year_from and query.year_to and query.year_from > query.year_to:
            raise InvalidProviderRequest("starting year must not be after ending year")
        query = replace(
            query,
            page=max(1, query.page),
            per_page=max(1, min(query.per_page, MAX_SEARCH_PAGE_SIZE)),
        )
        definition.require_credentials(self._config, "search")
        try:
            result = await definition.search_adapter.search(
                self._transport,
                query,
                settings=self._config,
                endpoint=definition.endpoint,
            )
        except RemoteNotFound:
            return CandidatePage(definition.name, (), 0, query.page, query.per_page)
        except InquiroError:
            raise
        except (TypeError, ValueError) as error:
            raise ProviderUnavailable(
                "metadata provider returned invalid search results"
            ) from error
        return replace(
            result, results=tuple(_normalize_candidate(record) for record in result.results)
        )

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
            (provider for provider in self._providers if provider.accepts_identifier(alias)),
            None,
        )

    def _require_open(self) -> None:
        if self._closed:
            raise RuntimeError("provider runtime is closed")
