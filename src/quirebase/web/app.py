from __future__ import annotations

import base64
import hashlib
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import HTMLResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal, engine
from quirebase.core.logging import configure_logging, log_context
from quirebase.mcp import SessionFactory, create_mcp_http_mount
from quirebase.web.api.common import API_ERROR_RESPONSES
from quirebase.web.api.routes import router as api_router
from quirebase.web.errors import register_error_handlers
from quirebase.web.system import router as system_router

if TYPE_CHECKING:
    from collections.abc import Callable

PACKAGE_DIR = Path(__file__).resolve().parent.parent
SOURCE_FRONTEND_DIRECTORY = PACKAGE_DIR.parent.parent / "frontend" / "build"
PACKAGED_FRONTEND_DIRECTORY = PACKAGE_DIR.parent / "quirebase_frontend"
SPA_EXCLUDED_PREFIXES = ("/api/", "/mcp")
DOCUMENTATION_SCRIPT_SOURCES = ("'self'", "https://cdn.jsdelivr.net")
DOCUMENTATION_STYLE_SOURCES = (
    "'self'",
    "'unsafe-inline'",
    "https://cdn.jsdelivr.net",
    "https://fonts.googleapis.com",
)
DOCUMENTATION_FONT_SOURCES = ("'self'", "data:", "https://fonts.gstatic.com")
DOCUMENTATION_IMAGE_SOURCES = ("'self'", "data:", "https://fastapi.tiangolo.com")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
_CSP_PATTERN = re.compile(
    r'<meta\s+http-equiv="content-security-policy"\s+content="([^"]+)"',
    re.IGNORECASE,
)
_SCRIPT_PATTERN = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.DOTALL | re.IGNORECASE)


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


def _inline_script_hashes(html: str) -> list[str]:
    hashes = []
    for attributes, body in _SCRIPT_PATTERN.findall(html):
        if "src=" in attributes.lower():
            continue
        digest = hashlib.sha256(body.encode("utf-8")).digest()
        hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
    return hashes


def _documentation_content_security_policy(html: str) -> str:
    directives = (
        ("default-src", ["'self'"]),
        ("script-src", [*DOCUMENTATION_SCRIPT_SOURCES, *_inline_script_hashes(html)]),
        ("style-src", list(DOCUMENTATION_STYLE_SOURCES)),
        ("img-src", list(DOCUMENTATION_IMAGE_SOURCES)),
        ("font-src", list(DOCUMENTATION_FONT_SOURCES)),
        ("connect-src", ["'self'"]),
        ("object-src", ["'none'"]),
        ("base-uri", ["'none'"]),
        ("form-action", ["'self'"]),
        ("frame-ancestors", ["'none'"]),
    )
    return "; ".join(f"{name} {' '.join(sources)}" for name, sources in directives)


def _documentation_pages(app: FastAPI) -> dict[str, Callable[[str], str]]:
    openapi_url = app.openapi_url or "/openapi.json"
    oauth2_redirect_url = app.swagger_ui_oauth2_redirect_url or "/docs/oauth2-redirect"

    def swagger_ui(root_path: str) -> str:
        response = get_swagger_ui_html(
            openapi_url=root_path + openapi_url,
            title=f"{app.title} - Swagger UI",
            oauth2_redirect_url=root_path + oauth2_redirect_url,
            init_oauth=app.swagger_ui_init_oauth,
            swagger_ui_parameters=app.swagger_ui_parameters,
        )
        return bytes(response.body).decode("utf-8")

    def redoc(root_path: str) -> str:
        response = get_redoc_html(
            openapi_url=root_path + openapi_url,
            title=f"{app.title} - ReDoc",
        )
        return bytes(response.body).decode("utf-8")

    def oauth2_redirect(_root_path: str) -> str:
        return bytes(get_swagger_ui_oauth2_redirect_html().body).decode("utf-8")

    return {
        "/docs": swagger_ui,
        oauth2_redirect_url: oauth2_redirect,
        "/redoc": redoc,
    }


def _documentation_endpoint(render: Callable[[str], str]) -> Callable[[Request], HTMLResponse]:
    def endpoint(request: Request) -> HTMLResponse:
        root_path = request.scope.get("root_path", "").rstrip("/")
        html = render(root_path)
        return HTMLResponse(
            html,
            headers={"Content-Security-Policy": _documentation_content_security_policy(html)},
        )

    return endpoint


def create_app(*, mcp_session_factory: SessionFactory = AsyncSessionLocal) -> FastAPI:
    settings = get_settings()
    frontend_directory = _frontend_directory()
    frontend_csp = _frontend_content_security_policy(frontend_directory)
    app = FastAPI(title="Quirebase", version="0.1.0", docs_url=None, redoc_url=None)
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
        content_type = response.headers.get("content-type", "")
        if (
            frontend_csp is not None
            and content_type.startswith("text/html")
            and "Content-Security-Policy" not in response.headers
            and not request.url.path.startswith(SPA_EXCLUDED_PREFIXES)
        ):
            response.headers["Content-Security-Policy"] = frontend_csp
        authenticated_api_response = request.url.path == "/api/v1/session" or (
            request.url.path.startswith("/api/v1/") and settings.session_cookie in request.cookies
        )
        if authenticated_api_response:
            if response.headers.get("cache-control") != "private, no-cache":
                response.headers["Cache-Control"] = "private, no-store"
        elif content_type.startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        elif request.url.path.startswith("/_app/immutable/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    register_error_handlers(app)

    for documentation_path, render in _documentation_pages(app).items():
        app.add_route(
            documentation_path,
            _documentation_endpoint(render),
            methods=["GET"],
            include_in_schema=False,
        )

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
