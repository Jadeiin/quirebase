from typing import Any

from pydantic import BaseModel


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


class WorkflowStatusView(BaseModel):
    id: str
    state: str
    error: str | None = None
