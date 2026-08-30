from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone


def as_utc(value: datetime) -> datetime:
    """Normalize persisted timestamps, treating SQLite's naive values as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def resolve_timezone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


def server_timezone() -> ZoneInfo:
    return get_localzone()


def annotation_export_timezone(name: str | None) -> ZoneInfo:
    return resolve_timezone(name) or server_timezone()
