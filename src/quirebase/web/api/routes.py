"""Compose the versioned HTTP API from capability-owned routers."""

from __future__ import annotations

from fastapi import APIRouter

from quirebase.web.api.account import router as account_router
from quirebase.web.api.admin import router as admin_router
from quirebase.web.api.annotations import router as annotations_router
from quirebase.web.api.content import router as content_router
from quirebase.web.api.dashboard import router as dashboard_router
from quirebase.web.api.discovery import router as discovery_router
from quirebase.web.api.exports import router as exports_router
from quirebase.web.api.imports import router as imports_router
from quirebase.web.api.items import router as items_router
from quirebase.web.api.library import router as library_router
from quirebase.web.api.library_exports import router as library_exports_router
from quirebase.web.api.projects import router as projects_router
from quirebase.web.api.session import router as session_router
from quirebase.web.api.tools import router as tools_router
from quirebase.web.api.workflows import router as workflows_router

router = APIRouter()
router.include_router(session_router)
router.include_router(dashboard_router)
router.include_router(library_router)
router.include_router(library_exports_router)
router.include_router(imports_router)
router.include_router(projects_router)
router.include_router(annotations_router)
router.include_router(discovery_router)
router.include_router(workflows_router)
router.include_router(account_router)
router.include_router(admin_router)
router.include_router(content_router)
router.include_router(exports_router)
router.include_router(items_router)
router.include_router(tools_router)
