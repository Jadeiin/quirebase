from typing import Any

from pydantic import BaseModel, Field

from quirebase.access import effective_system_actions


class ErrorField(BaseModel):
    path: list[str | int]
    code: str
    message: str


class ApiErrorView(BaseModel):
    code: str
    message: str
    fields: list[ErrorField] | None = None
    meta: dict[str, Any] | None = None


API_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "default": {"model": ApiErrorView},
    # Python 3.12 and 3.14 use different HTTPStatus phrases for 422. Keep the
    # generated OpenAPI contract deterministic across supported runtimes.
    422: {"model": ApiErrorView, "description": "Unprocessable Content"},
}


class WriteResult(BaseModel):
    id: str
    version: int | None = None


class OkView(BaseModel):
    ok: bool = True


class AuthorizationView(BaseModel):
    """Canonical resource-action keys; clients check this set, never reconstruct policy."""

    allowed: list[str]
    relations: dict[str, list[str]] = Field(default_factory=dict)


def system_authorization_view(role: str) -> AuthorizationView:
    return AuthorizationView(
        allowed=sorted(action.value for action in effective_system_actions(role)),
    )


class WorkflowStatusView(BaseModel):
    id: str
    state: str
    error: str | None = None
