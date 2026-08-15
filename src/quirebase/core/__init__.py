from __future__ import annotations

from quirebase.core.config import Settings, get_settings
from quirebase.core.database import Base, SessionLocal, engine, get_db, make_engine
from quirebase.core.errors import (
    DomainError,
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.i18n import DEFAULT_LOCALE, catalog, translate

__all__ = [
    "DEFAULT_LOCALE",
    "Base",
    "DomainError",
    "PermissionDenied",
    "ResourceNotFound",
    "ResourceUnavailable",
    "SessionLocal",
    "Settings",
    "ValidationFailure",
    "VersionConflict",
    "catalog",
    "engine",
    "get_db",
    "get_settings",
    "make_engine",
    "translate",
]
