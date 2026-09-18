from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal, engine
from quirebase.core.logging import configure_logging, log_context
from quirebase.mcp import SessionFactory, create_mcp_http_mount
from quirebase.web.api.common import API_ERROR_RESPONSES
from quirebase.web.api.routes import router as api_router
from quirebase.web.errors import register_error_handlers
from quirebase.web.system import router as system_router

PACKAGE_DIR = Path(__file__).resolve().parent.parent
SOURCE_FRONTEND_DIRECTORY = PACKAGE_DIR.parent.parent / "frontend" / "build"
PACKAGED_FRONTEND_DIRECTORY = PACKAGE_DIR.parent / "quirebase_frontend"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_CSP_PATTERN = re.compile(
    r'<meta\s+http-equiv="content-security-policy"\s+content="([^"]+)"',
    re.IGNORECASE,
)


def _frontend_directory() -> Path:
    for directory in (SOURCE_FRONTEND_DIRECTORY, PACKAGED_FRONTEND_DIRECTORY):
        if (directory / "index.html").is_file():
            return directory
    if os.environ.get("FASTAPI_ENV") == "development":
        return SOURCE_FRONTEND_DIRECTORY
    raise RuntimeError(
        "frontend build not found; run `bun run --cwd frontend build` before starting Quirebase"
    )


def _frontend_content_security_policy(directory: Path) -> str | None:
    index = directory / "index.html"
    if not index.is_file() and os.environ.get("FASTAPI_ENV") == "development":
        return None
    match = _CSP_PATTERN.search(index.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError(f"frontend build has no Content Security Policy: {index}")
    return match.group(1)


def create_app(*, mcp_session_factory: SessionFactory = AsyncSessionLocal) -> FastAPI:
    settings = get_settings()
    frontend_directory = _frontend_directory()
    frontend_csp = _frontend_content_security_policy(frontend_directory)
    app = FastAPI(title="Quirebase", version="0.1.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid4().hex
        )
        with log_context(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        if frontend_csp is not None:
            response.headers["Content-Security-Policy"] = frontend_csp
        content_type = response.headers.get("content-type", "")
        if request.url.path == "/api/v1/session" or (
            request.url.path.startswith("/api/v1/") and settings.session_cookie in request.cookies
        ):
            response.headers["Cache-Control"] = "private, no-store"
        elif content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif request.url.path.startswith("/_app/immutable/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    register_error_handlers(app)

    app.include_router(system_router)
    app.include_router(api_router, responses=API_ERROR_RESPONSES)

    mcp_http = create_mcp_http_mount(
        app,
        mcp_session_factory,
        allowed_hosts=settings.allowed_host_list,
        settings=settings,
    )
    app.state.mcp_server = mcp_http.server

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_logging(
            level=settings.log_level,
            json_output=settings.log_format == "json",
        )
        try:
            async with mcp_http.lifespan():
                yield
        finally:
            if mcp_session_factory is AsyncSessionLocal:
                await engine.dispose()

    app.router.lifespan_context = lifespan

    @app.api_route(
        "/api/v1/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    def api_not_found(path: str) -> None:
        del path
        raise HTTPException(status_code=404, detail="not found")

    app.mount("/mcp", mcp_http.app, name="mcp")
    app.frontend(
        "/",
        directory=frontend_directory,
        fallback="index.html",
        check_dir="auto",
    )

    return app


app = create_app()
