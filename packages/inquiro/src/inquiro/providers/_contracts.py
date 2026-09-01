from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from inquiro.models import (
    AcquiredDocument,
    Identifier,
    ProviderConfig,
    ProviderRecord,
    ProviderSearchPage,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.transport import RemoteNotFound

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport

__all__ = ["RemoteNotFound"]

type IdentifierParser = Callable[[str, str], Identifier | None]
type ProviderCapability = Literal["lookup", "search", "document"]


class LookupImplementation(Protocol):
    async def lookup(
        self,
        client: ProviderContext,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> ProviderRecord: ...


class SearchImplementation(Protocol):
    async def search(
        self,
        client: ProviderContext,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: ProviderConfig,
        endpoint: str,
    ) -> ProviderSearchPage: ...


class DocumentImplementation(Protocol):
    async def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument: ...


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    display_name: str | None = None
    identifier_aliases: tuple[str, ...] = ()
    identifier_parser: IdentifierParser | None = None
    auto_detect_identifier: bool = False
    search_adapter: SearchImplementation | None = None
    lookup_adapter: LookupImplementation | None = None
    document_adapter: DocumentImplementation | None = None
    endpoint: str = ""
    document_endpoint: str = ""
    credential_setting: str | None = None
    credential_environment: str | None = None
    credential_capabilities: frozenset[ProviderCapability] = frozenset({"lookup", "search"})

    def require_credentials(
        self,
        config: ProviderConfig,
        capability: ProviderCapability,
    ) -> None:
        if (
            capability in self.credential_capabilities
            and self.credential_setting
            and not getattr(config, self.credential_setting)
        ):
            raise ProviderUnavailable(
                f"{self.display_name or self.name} requires "
                f"{self.credential_environment or self.credential_setting}"
            )


class ProviderContext:
    def __init__(self, transport: BoundedTransport) -> None:
        self._transport = transport

    async def _get(
        self,
        url: str,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return await self._transport.get(url, params, headers)

    async def _download_pdf(
        self,
        url: str,
        *,
        filename: str | None = None,
        provider: str | None = None,
    ) -> AcquiredDocument:
        return await self._transport.download_pdf(url, filename=filename, provider=provider)
