from __future__ import annotations

import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from quirebase.accounts.invitations import InvitationConflict
from quirebase.accounts.throttling import LoginThrottled
from quirebase.core.errors import (
    DomainError,
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    SizeLimitExceeded,
    ValidationFailure,
    VersionConflict,
)
from quirebase.documents.annotations import DocumentNotReady
from quirebase.documents.revisions import UnsupportedMediaType
from quirebase.library import BatchConflict, TagConflict, UpstreamServiceError
from quirebase.projects.members import ProjectMemberConflict
from quirebase.web.api.common import ApiErrorView, ErrorField

logger = logging.getLogger(__name__)


class ApiHTTPException(HTTPException):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        headers: dict[str, str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = code
        self.message = message
        self.meta = meta


def _error_response(
    status_code: int,
    code: str,
    message: str,
    *,
    fields: list[ErrorField] | None = None,
    meta: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    error = ApiErrorView(code=code, message=message, fields=fields, meta=meta)
    return JSONResponse(
        status_code=status_code,
        content=error.model_dump(exclude_none=True),
        headers=headers,
    )


def _domain_error(exc: DomainError) -> tuple[int, str, str, dict[str, Any] | None]:
    if isinstance(exc, LoginThrottled):
        return 429, "login_throttled", str(exc) or "too many login attempts; try again later", None
    if isinstance(exc, InvitationConflict):
        return 409, "invitation_conflict", str(exc) or "invitation conflict", None
    if isinstance(exc, TagConflict):
        return 409, "tag_conflict", str(exc) or "Tag conflict", None
    if isinstance(exc, ProjectMemberConflict):
        return 409, "project_member_conflict", str(exc) or "Project member conflict", None
    if isinstance(exc, DocumentNotReady):
        return 409, "document_not_ready", str(exc) or "document not ready", None
    if isinstance(exc, BatchConflict):
        return 409, "import_batch_conflict", str(exc) or "Import Batch conflict", None
    if isinstance(exc, UnsupportedMediaType):
        return 415, "unsupported_media_type", str(exc) or "unsupported media type", None
    if isinstance(exc, UpstreamServiceError):
        return 502, "upstream_service_error", str(exc) or "upstream service error", None
    if isinstance(exc, ResourceUnavailable):
        return 404, "not_found", "not found", None
    if isinstance(exc, ResourceNotFound):
        return 404, "not_found", str(exc) or "not found", None
    if isinstance(exc, PermissionDenied):
        return 403, "permission_denied", str(exc) or "permission denied", None
    if isinstance(exc, ValidationFailure):
        return 422, "validation_failed", str(exc) or "validation failure", None
    if isinstance(exc, SizeLimitExceeded):
        return 413, "content_too_large", str(exc) or "content too large", None
    if isinstance(exc, VersionConflict):
        return 409, "version_conflict", str(exc), {"version": exc.current_version}
    return 400, "domain_error", str(exc), None


_HTTP_ERROR_CODES = {
    400: "invalid_request",
    401: "authentication_required",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "content_too_large",
    415: "unsupported_media_type",
    416: "range_not_satisfiable",
    422: "validation_failed",
    429: "rate_limited",
    502: "upstream_service_error",
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError):  # ruff: ignore[unused-async]
        status_code, code, message, meta = _domain_error(exc)
        return _error_response(status_code, code, message, meta=meta)

    @app.exception_handler(RequestValidationError)
    def handle_request_validation(_request: Request, exc: RequestValidationError):
        fields = [
            ErrorField(
                path=list(error["loc"]),
                code=error["type"],
                message=error["msg"],
            )
            for error in exc.errors()
        ]
        return _error_response(
            422,
            "validation_failed",
            "request validation failed",
            fields=fields,
        )

    @app.exception_handler(StarletteHTTPException)
    def handle_http_error(_request: Request, exc: StarletteHTTPException):
        if isinstance(exc, ApiHTTPException):
            return _error_response(
                exc.status_code,
                exc.code,
                exc.message,
                meta=exc.meta,
                headers=dict(exc.headers) if exc.headers else None,
            )
        message = str(exc.detail) if exc.detail else HTTPStatus(exc.status_code).phrase
        return _error_response(
            exc.status_code,
            _HTTP_ERROR_CODES.get(exc.status_code, "request_failed"),
            message,
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(Exception)
    def handle_unexpected_error(request: Request, exc: Exception):
        if request.url.path != "/api/v1" and not request.url.path.startswith("/api/v1/"):
            raise exc
        logger.error(
            "unexpected API error",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return _error_response(
            500,
            "internal_error",
            "internal server error",
        )
