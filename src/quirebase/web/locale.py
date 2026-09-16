from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request

DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = ("en-US", "zh-CN")


def normalize_locale(value: str) -> str:
    """Return the supported BCP 47 locale closest to *value*."""
    normalized = value.strip().replace("_", "-").casefold()
    for locale in SUPPORTED_LOCALES:
        if (
            normalized == locale.casefold()
            or normalized.split("-", 1)[0] == locale.split("-", 1)[0]
        ):
            return locale
    return DEFAULT_LOCALE


def resolve_request_locale(request: Request) -> str:
    if cookie_locale := request.cookies.get("quirebase_locale"):
        return normalize_locale(cookie_locale)
    weighted: list[tuple[float, int, str]] = []
    for index, entry in enumerate(request.headers.get("accept-language", "").split(",")):
        language, *parameters = entry.strip().split(";")
        quality = 1.0
        for parameter in parameters:
            if parameter.strip().startswith("q="):
                try:
                    quality = float(parameter.strip()[2:])
                except ValueError:
                    quality = 0.0
        if language and language != "*" and quality > 0:
            weighted.append((quality, -index, language))
    for _quality, _position, language in sorted(weighted, reverse=True):
        candidate = normalize_locale(language)
        if candidate != DEFAULT_LOCALE or language.casefold().startswith("en"):
            return candidate
    return DEFAULT_LOCALE
