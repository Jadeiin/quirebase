from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterator

ProgrammaticProtocol = Literal["http", "mcp"]


@dataclass
class ProgrammaticInvocation:
    """Request-local source metadata shared with business Audit Events."""

    protocol: ProgrammaticProtocol
    operation: str
    api_token_id: str | None = None
    client_id: str | None = None

    def detail(self) -> dict[str, str]:
        values = {"protocol": self.protocol, "operation": self.operation}
        if self.api_token_id is not None:
            values["api_token_id"] = self.api_token_id
        if self.client_id is not None:
            values["client_id"] = self.client_id
        return values


_current_invocation: ContextVar[ProgrammaticInvocation | None] = ContextVar(
    "programmatic_invocation", default=None
)


@contextmanager
def programmatic_invocation(
    protocol: ProgrammaticProtocol,
    operation: str,
    *,
    api_token_id: str | None = None,
    client_id: str | None = None,
) -> Iterator[ProgrammaticInvocation]:
    """Bind source metadata while an inbound adapter invokes business behaviour."""
    invocation = ProgrammaticInvocation(
        protocol=protocol,
        operation=operation,
        api_token_id=api_token_id,
        client_id=client_id,
    )
    marker = _current_invocation.set(invocation)
    try:
        yield invocation
    finally:
        _current_invocation.reset(marker)


def identify_programmatic_invocation(*, api_token_id: str, client_id: str) -> None:
    """Attach the verified credential without exposing it to business interfaces."""
    invocation = _current_invocation.get()
    if invocation is not None:
        invocation.api_token_id = api_token_id
        invocation.client_id = client_id


def current_programmatic_invocation() -> ProgrammaticInvocation | None:
    return _current_invocation.get()
