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


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LoginThrottled)
    def handle_login_throttled(request: Request, exc: LoginThrottled):
        raise HTTPException(
            status_code=429, detail=str(exc) or "too many login attempts; try again later"
        )

    @app.exception_handler(InvitationConflict)
    def handle_invitation_conflict(request: Request, exc: InvitationConflict):
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(TagConflict)
    def handle_tag_conflict(request: Request, exc: TagConflict):
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(ProjectMemberConflict)
    def handle_project_member_conflict(request: Request, exc: ProjectMemberConflict):
        raise HTTPException(status_code=409, detail=str(exc) or "conflict")

    @app.exception_handler(DocumentNotReady)
    def handle_document_not_ready(request: Request, exc: DocumentNotReady):
        raise HTTPException(status_code=409, detail=str(exc) or "document not ready")

    @app.exception_handler(BatchConflict)
    def handle_batch_conflict(request: Request, exc: BatchConflict):
        raise HTTPException(status_code=409, detail=str(exc) or "batch conflict")

    @app.exception_handler(UnsupportedMediaType)
    def handle_unsupported_media(request: Request, exc: UnsupportedMediaType):
        raise HTTPException(status_code=415, detail=str(exc) or "unsupported media type")

    @app.exception_handler(UpstreamServiceError)
    def handle_upstream_service_error(request: Request, exc: UpstreamServiceError):
        raise HTTPException(status_code=502, detail=str(exc) or "upstream service error")

    @app.exception_handler(ResourceNotFound)
    def handle_not_found(request: Request, exc: ResourceNotFound):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(status_code=404, content={"detail": str(exc) or "not found"})
        raise HTTPException(status_code=404, detail=str(exc) or "not found")

    @app.exception_handler(ResourceUnavailable)
    def handle_unavailable(request: Request, exc: ResourceUnavailable):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        raise HTTPException(status_code=404, detail="not found")

    @app.exception_handler(PermissionDenied)
    def handle_permission_denied(request: Request, exc: PermissionDenied):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(
                status_code=403, content={"detail": str(exc) or "permission denied"}
            )
        raise HTTPException(status_code=403, detail=str(exc) or "permission denied")

    @app.exception_handler(ValidationFailure)
    def handle_validation_failure(request: Request, exc: ValidationFailure):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(
                status_code=422, content={"detail": str(exc) or "validation failure"}
            )
        raise HTTPException(status_code=422, detail=str(exc) or "validation failure")

    @app.exception_handler(SizeLimitExceeded)
    def handle_size_limit_exceeded(request: Request, exc: SizeLimitExceeded):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(
                status_code=413, content={"detail": str(exc) or "content too large"}
            )
        raise HTTPException(status_code=413, detail=str(exc) or "content too large")

    @app.exception_handler(VersionConflict)
    def handle_version_conflict(request: Request, exc: VersionConflict):
        if request.url.path.startswith("/documents/") or "application/json" in request.headers.get(
            "accept", ""
        ):
            return JSONResponse(
                status_code=409,
                content={"detail": {"version": exc.current_version}},
            )
        raise HTTPException(
            status_code=409,
            detail={"version": exc.current_version},
        )

    @app.exception_handler(DomainError)
    def handle_generic_domain_error(request: Request, exc: DomainError):
        raise HTTPException(status_code=400, detail=str(exc))
