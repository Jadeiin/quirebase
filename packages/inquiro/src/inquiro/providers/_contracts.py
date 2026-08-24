from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from inquiro.models import (
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


class LookupImplementation(Protocol):
    def lookup(
        self,
        client: ProviderContext,
        value: str,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> ProviderRecord: ...


class SearchImplementation(Protocol):
    def search(
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


@dataclass(frozen=True)
class ProviderDefinition:
    name: str
    display_name: str | None = None
    identifier_aliases: tuple[str, ...] = ()
    identifier_parser: IdentifierParser | None = None
    auto_detect_identifier: bool = False
    search_adapter: SearchImplementation | None = None
    lookup_adapter: LookupImplementation | None = None
    endpoint: str = ""
    credential_setting: str | None = None
    credential_environment: str | None = None

    def require_credentials(self, config: ProviderConfig) -> None:
        if self.credential_setting and not getattr(config, self.credential_setting):
            raise ProviderUnavailable(
                f"{self.display_name or self.name} requires "
                f"{self.credential_environment or self.credential_setting}"
            )


class ProviderContext:
    def __init__(self, transport: BoundedTransport) -> None:
        self._transport = transport

    def _get(
        self,
        url: str,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return self._transport.get(url, params, headers)
