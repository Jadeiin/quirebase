from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from inquiro.models import (
    AcquiredDocument,
    CandidatePage,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    ProviderUnavailable,
    SearchQuery,
    SearchSort,
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
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord: ...


class SearchImplementation(Protocol):
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage: ...


class DocumentImplementation(Protocol):
    async def acquire(
        self,
        client: BoundedTransport,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> AcquiredDocument: ...


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    identifier_namespace: str
    display_name: str | None = None
    identifier_parser: IdentifierParser | None = None
    auto_detect_identifier: bool = False
    search_adapter: SearchImplementation | None = None
    search_sorts: tuple[SearchSort, ...] = ("relevance", "published")
    lookup_adapter: LookupImplementation | None = None
    document_adapter: DocumentImplementation | None = None
    endpoint: str = ""
    document_endpoint: str = ""
    credential_setting: str | None = None
    credential_environment: str | None = None
    credential_capabilities: frozenset[ProviderCapability] = frozenset({"lookup", "search"})
    additional_lookup_namespaces: tuple[str, ...] = ()

    def accepts_identifier(self, provider: str) -> bool:
        return provider in {self.name, self.identifier_namespace}

    def require_credentials(
        self,
        config: ProviderConfig,
        capability: ProviderCapability,
    ) -> None:
        if not self.has_credentials(config, capability):
            raise ProviderUnavailable(
                f"{self.display_name or self.name} requires "
                f"{self.credential_environment or self.credential_setting}"
            )

    def has_credentials(self, config: ProviderConfig, capability: ProviderCapability) -> bool:
        return not (
            capability in self.credential_capabilities
            and self.credential_setting
            and not getattr(config, self.credential_setting)
        )
