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
from quirebase.core.i18n import (
    DEFAULT_LOCALE,
    catalog,
    format_date,
    format_datetime,
    format_number,
    gettext,
    negotiate_locale,
    ngettext,
    pgettext,
    translate,
)

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
    "format_date",
    "format_datetime",
    "format_number",
    "get_db",
    "get_settings",
    "gettext",
    "make_engine",
    "negotiate_locale",
    "ngettext",
    "pgettext",
    "translate",
]
