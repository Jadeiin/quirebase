from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from quirebase.core.config import get_settings
from quirebase.core.database import AsyncSessionLocal, engine
from quirebase.mcp import SessionFactory, create_mcp_http_mount
from quirebase.web.api.routes import router as api_router
from quirebase.web.errors import register_error_handlers
from quirebase.web.json.annotations import router as json_annotations_router
from quirebase.web.json.documents import router as json_documents_router
from quirebase.web.json.exports import router as json_exports_router
from quirebase.web.views.admin import router as views_admin_router
from quirebase.web.views.auth import public_router as views_auth_public_router
from quirebase.web.views.auth import router as views_auth_router
from quirebase.web.views.dashboard import router as views_dashboard_router
from quirebase.web.views.discovery import router as views_discovery_router
from quirebase.web.views.items import router as views_items_router
from quirebase.web.views.library import router as views_library_router
from quirebase.web.views.projects import router as views_projects_router
from quirebase.web.views.system import public_router as views_system_public_router
from quirebase.web.views.system import router as views_system_router
from quirebase.web.views.tools import router as views_tools_router

PACKAGE_DIR = Path(__file__).resolve().parent.parent


def create_app(*, mcp_session_factory: SessionFactory = AsyncSessionLocal) -> FastAPI:
    settings = get_settings()
    mcp_http = create_mcp_http_mount(
        mcp_session_factory,
        allowed_hosts=settings.allowed_host_list,
        settings=settings,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            async with mcp_http.server.session_manager.run():
                yield
        finally:
            if mcp_session_factory is AsyncSessionLocal:
                await engine.dispose()

    app = FastAPI(title="Quirebase", version="0.1.0", lifespan=lifespan)
    app.state.mcp_server = mcp_http.server
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' https: http:; worker-src 'self' blob:; "
            "object-src 'none'; frame-ancestors 'none'"
        )
        return response

    register_error_handlers(app)

    # Views (public_router holds the pre-authentication endpoints exempt from CSRF)
    app.include_router(views_system_public_router)
    app.include_router(views_auth_public_router)
    app.include_router(views_system_router)
    app.include_router(views_auth_router)
    app.include_router(views_admin_router)
    app.include_router(views_dashboard_router)
    app.include_router(views_library_router)
    app.include_router(views_projects_router)
    app.include_router(views_items_router)
    app.include_router(views_discovery_router)
    app.include_router(views_tools_router)

    # JSON / Binary APIs
    app.include_router(api_router)
    app.include_router(json_documents_router)
    app.include_router(json_annotations_router)
    app.include_router(json_exports_router)

    app.mount("/mcp", mcp_http.app, name="mcp")

    return app


app = create_app()
