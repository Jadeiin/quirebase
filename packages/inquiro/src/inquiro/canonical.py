"""Canonical text helpers shared by Provider payload parsing and the host application."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from dateutil.parser import parse, parserinfo

from inquiro.richtext import convert_rich_text

__all__ = [
    "clean_markup",
    "clean_rich_markup",
    "first_text",
    "normalize_publication_date",
]

_DATE_INFO = parserinfo(yearfirst=True)
_DATE_BASE = datetime(2000, 1, 1)
_DATE_PROBE = datetime(2000, 2, 2)


def first_text(value: Any) -> str | None:
    """Collapse a scalar or first list element into single-spaced text."""
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def clean_markup(value: str | None) -> str | None:
    """Strip markup from provider text and collapse whitespace; None for empty results."""
    if not value:
        return None
    return first_text(convert_rich_text(value, source="html", target="text"))


def clean_rich_markup(value: str | None) -> str | None:
    """Canonicalize provider text to balanced rich-text HTML; None when it renders empty."""
    if not value:
        return None
    canonical = first_text(convert_rich_text(value, source="html", target="html"))
    if not canonical or not convert_rich_text(canonical, source="html", target="text"):
        return None
    return canonical


def normalize_publication_date(value: Any) -> str | None:
    """Project upstream dates onto year, month or day precision without inventing parts."""
    text = first_text(value)
    if not text:
        return None
    numeric = re.fullmatch(
        r"(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?/?"
        r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?",
        text,
    )
    year_tokens = [numeric[1]] if numeric else re.findall(r"\b\d{4}\b", text)
    years = set(year_tokens)
    if len(years) != 1 or not 1 <= (year := int(years.pop())) <= 9999:
        return None
    try:
        if numeric:
            parts = [int(part) for part in numeric.groups() if part is not None]
            # Validate ISO components directly; a parser may swap an invalid month and day.
            return date(*(parts + [1] * (3 - len(parts)))).isoformat()[: 4 + 3 * (len(parts) - 1)]
        if len(year_tokens) == 1 and not re.search(r"\d\s*[-/\u2013\u2014]\s*\d", text):
            parsed = parse(text, parserinfo=_DATE_INFO, default=_DATE_BASE)
            probe = parse(text, parserinfo=_DATE_INFO, default=_DATE_PROBE)
            # Only omitted components change when the parser's default changes.
            if parsed.year == year:
                precision = (
                    4 if parsed.month != probe.month else 7 if parsed.day != probe.day else 10
                )
                return parsed.date().isoformat()[:precision]
    except (ValueError, OverflowError):
        pass
    # Ranges and invalid dates retain only their shared, explicit year/month.
    months = {
        month
        for token in re.findall(r"[A-Za-z]+", text)
        if (month := _DATE_INFO.month(token)) is not None
    }
    months.update(int(month) for month in re.findall(r"\b\d{4}[-/](\d{1,2})\b", text))
    month = months.pop() if len(months) == 1 else None
    return f"{year:04d}-{month:02d}" if month is not None and 1 <= month <= 12 else f"{year:04d}"
