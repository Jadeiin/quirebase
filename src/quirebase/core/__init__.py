from __future__ import annotations

from quirebase.core.config import Settings, get_settings
from quirebase.core.database import (
    AsyncSessionLocal,
    Base,
    async_database_url,
    engine,
    get_db,
    is_sqlite_database_url,
    make_async_engine,
)
from quirebase.core.errors import (
    DomainError,
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    UpstreamServiceError,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.i18n import (
    DEFAULT_LOCALE,
    _,
    format_date,
    format_datetime,
    format_number,
    gettext,
    negotiate_locale,
    ngettext,
    pgettext,
)

__all__ = [
    "DEFAULT_LOCALE",
    "AsyncSessionLocal",
    "Base",
    "DomainError",
    "PermissionDenied",
    "ResourceNotFound",
    "ResourceUnavailable",
    "Settings",
    "UpstreamServiceError",
    "ValidationFailure",
    "VersionConflict",
    "_",
    "async_database_url",
    "engine",
    "format_date",
    "format_datetime",
    "format_number",
    "get_db",
    "get_settings",
    "gettext",
    "is_sqlite_database_url",
    "make_async_engine",
    "negotiate_locale",
    "ngettext",
    "pgettext",
]
