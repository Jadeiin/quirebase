from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING

from babel.dates import format_date as babel_format_date
from babel.dates import format_datetime as babel_format_datetime
from babel.support import NullTranslations, Translations

if TYPE_CHECKING:
    from datetime import date, datetime

DEFAULT_LOCALE = "en_US"
LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


def normalize_locale(locale: str) -> str:
    """Normalize locale strings like 'zh-CN', 'zh_CN', 'en-US' to standard gettext directory name 'zh_CN'."""
    if not locale:
        return "en_US"
    clean = locale.replace("-", "_")
    parts = clean.split("_")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}_{parts[1].upper()}"


def bcp47_tag(locale: str = DEFAULT_LOCALE) -> str:
    """Render a locale as a BCP 47 language tag for HTML (zh_CN -> zh-CN)."""
    return normalize_locale(locale).replace("_", "-")


@cache
def get_translations(locale: str = DEFAULT_LOCALE) -> Translations | NullTranslations:
    """Load GNUTranslations with in-memory caching."""
    import contextlib

    norm = normalize_locale(locale)
    with contextlib.suppress(Exception):
        trans = Translations.load(LOCALES_DIR, [norm])
        if trans is not None:
            return trans
    return NullTranslations()


def _interpolate(translated: str, values: dict[str, object]) -> str:
    """Interpolate {field} placeholders, returning the raw text if any field is unknown."""
    if not values:
        return translated
    try:
        return translated.format(**values)
    except (KeyError, IndexError, ValueError):
        return translated


def gettext(message: str, locale: str = DEFAULT_LOCALE, **values: object) -> str:
    """Standard gettext translation with optional value interpolation."""
    if not message:
        return ""
    trans = get_translations(locale)
    return _interpolate(trans.gettext(message), values)


_ = gettext


def ngettext(singular: str, plural: str, n: int, locale: str = DEFAULT_LOCALE) -> str:
    """Plural translation using gettext plural rules."""
    trans = get_translations(locale)
    return trans.ngettext(singular, plural, n)


def pgettext(context: str, message: str, locale: str = DEFAULT_LOCALE, **values: object) -> str:
    """Contextual gettext translation with fallback to general message."""
    trans = get_translations(locale)
    if hasattr(trans, "pgettext"):
        res = trans.pgettext(context, message)
        if res != message:
            return _interpolate(str(res), values)
    return gettext(message, locale, **values)


def format_datetime(
    dt: datetime,
    format: str = "medium",
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Format datetime using Babel locale formatting."""
    norm = normalize_locale(locale)
    try:
        return babel_format_datetime(dt, format=format, locale=norm)
    except (ValueError, TypeError, LookupError):
        return dt.isoformat()


def format_date(
    d: date,
    format: str = "medium",
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Format date using Babel locale formatting."""
    norm = normalize_locale(locale)
    try:
        return babel_format_date(d, format=format, locale=norm)
    except (ValueError, TypeError, LookupError):
        return d.isoformat()


def format_number(
    number: float,
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Format number using Babel locale formatting."""
    from babel.numbers import format_decimal

    norm = normalize_locale(locale)
    try:
        return format_decimal(number, locale=norm)
    except (ValueError, TypeError, LookupError):
        return str(number)


def negotiate_locale(
    accept_language: str,
    supported_locales: list[str] | None = None,
    default: str = DEFAULT_LOCALE,
) -> str:
    """Negotiate best matching locale from HTTP Accept-Language header."""
    if not accept_language:
        return default
    if supported_locales is None:
        supported_locales = ["zh_CN", "en_US"]

    langs: list[str] = []
    for part in accept_language.split(","):
        tag = part.split(";", 1)[0].strip()
        if tag:
            langs.append(normalize_locale(tag))

    for lang in langs:
        for supp in supported_locales:
            if (
                lang.lower() == supp.lower()
                or lang.split("_")[0].lower() == supp.split("_")[0].lower()
            ):
                return supp
    return default
