from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import ValidationError

from quirebase.accounts import AuthenticationFailure, resolve_api_token_user
from quirebase.audit import programmatic_invocation
from quirebase.core.errors import DomainError, ResourceNotFound, ResourceUnavailable

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.mcp.auth import SessionFactory
    from quirebase.mcp.policy import ToolPolicy


@dataclass(frozen=True)
class RequestIdentity:
    user_id: str
    client_id: str = "internal"
    api_token_id: str | None = None


IdentityProvider = Callable[[], RequestIdentity]
Result = TypeVar("Result")


def api_token_request_identity() -> RequestIdentity:
    """Read the User identity verified from an Accounts-owned API Token."""
    token = get_access_token()
    if token is None or token.subject is None:
        raise ToolError("authentication required")
    client_id = token.client_id or "unknown"
    prefix = "quirebase-api-token:"
    api_token_id = client_id.removeprefix(prefix) if client_id.startswith(prefix) else None
    return RequestIdentity(
        user_id=token.subject,
        client_id=client_id,
        api_token_id=api_token_id,
    )


@dataclass(frozen=True)
class McpRuntime:
    """Authenticate once and adapt domain failures without owning business rules."""

    session_factory: SessionFactory
    identity_provider: IdentityProvider
    policy: ToolPolicy

    async def call(
        self,
        tool_name: str,
        operation: Callable[[AsyncSession, Any], Awaitable[Result]],
        *,
        conceal_resource: str | None = None,
    ) -> Result:
        self.policy.require(tool_name)
        identity = self.identity_provider()
        try:
            with programmatic_invocation(
                "mcp",
                tool_name,
                api_token_id=identity.api_token_id,
                client_id=identity.client_id,
            ):
                async with self.session_factory() as db:
                    user = await resolve_api_token_user(db, identity.user_id)
                    result = await operation(db, user)
        except AuthenticationFailure as error:
            raise ToolError("authentication required") from error
        except (ResourceNotFound, ResourceUnavailable) as error:
            raise ToolError(conceal_resource or str(error)) from error
        except ValidationError as error:
            raise ToolError(str(error)) from error
        except DomainError as error:
            raise ToolError(str(error)) from error
        return result
