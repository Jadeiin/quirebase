from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tzlocal import get_localzone


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
