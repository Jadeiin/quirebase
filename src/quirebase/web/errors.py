from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

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


def _expects_json(request: Request) -> bool:
    return request.url.path.startswith((
        "/api/",
        "/documents/",
    )) or "application/json" in request.headers.get("accept", "")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LoginThrottled)
    async def handle_login_throttled(request: Request, exc: LoginThrottled):  # ruff: ignore[unused-async]
        raise HTTPException(
            status_code=429, detail=str(exc) or "too many login attempts; try again later"
        )

    @app.exception_handler(InvitationConflict)
    async def handle_invitation_conflict(request: Request, exc: InvitationConflict):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(TagConflict)
    async def handle_tag_conflict(request: Request, exc: TagConflict):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(ProjectMemberConflict)
    async def handle_project_member_conflict(request: Request, exc: ProjectMemberConflict):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(DocumentNotReady)
    async def handle_document_not_ready(request: Request, exc: DocumentNotReady):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=409, detail=str(exc) or "document not ready")

    @app.exception_handler(BatchConflict)
    async def handle_batch_conflict(request: Request, exc: BatchConflict):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=409, detail=str(exc) or "batch conflict")

    @app.exception_handler(UnsupportedMediaType)
    async def handle_unsupported_media(request: Request, exc: UnsupportedMediaType):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=415, detail=str(exc) or "unsupported media type")

    @app.exception_handler(UpstreamServiceError)
    async def handle_upstream_service_error(request: Request, exc: UpstreamServiceError):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=502, detail=str(exc) or "upstream service error")

    @app.exception_handler(ResourceNotFound)
    async def handle_not_found(request: Request, exc: ResourceNotFound):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(status_code=404, content={"detail": str(exc) or "not found"})
        raise HTTPException(status_code=404, detail=str(exc) or "not found")

    @app.exception_handler(ResourceUnavailable)
    async def handle_unavailable(request: Request, exc: ResourceUnavailable):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        raise HTTPException(status_code=404, detail="not found")

    @app.exception_handler(PermissionDenied)
    async def handle_permission_denied(request: Request, exc: PermissionDenied):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(
                status_code=403, content={"detail": str(exc) or "permission denied"}
            )
        raise HTTPException(status_code=403, detail=str(exc) or "permission denied")

    @app.exception_handler(ValidationFailure)
    async def handle_validation_failure(request: Request, exc: ValidationFailure):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(
                status_code=422, content={"detail": str(exc) or "validation failure"}
            )
        raise HTTPException(status_code=422, detail=str(exc) or "validation failure")

    @app.exception_handler(SizeLimitExceeded)
    async def handle_size_limit_exceeded(request: Request, exc: SizeLimitExceeded):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(
                status_code=413, content={"detail": str(exc) or "content too large"}
            )
        raise HTTPException(status_code=413, detail=str(exc) or "content too large")

    @app.exception_handler(VersionConflict)
    async def handle_version_conflict(request: Request, exc: VersionConflict):  # ruff: ignore[unused-async]
        if _expects_json(request):
            return JSONResponse(
                status_code=409,
                content={"detail": {"version": exc.current_version}},
            )
        raise HTTPException(
            status_code=409,
            detail={"version": exc.current_version},
        )

    @app.exception_handler(DomainError)
    async def handle_generic_domain_error(request: Request, exc: DomainError):  # ruff: ignore[unused-async]
        raise HTTPException(status_code=400, detail=str(exc))
