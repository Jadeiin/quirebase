"""The built-in Citation Style catalog and CSL validation."""

from __future__ import annotations

import io
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from citeproc import (
        Citation,
        CitationItem,
        CitationStylesBibliography,
        CitationStylesStyle,
        formatter,
    )
    from citeproc.source.json import CiteProcJSON
except ImportError:
    Citation = None
    CitationItem = None
    CitationStylesBibliography = None
    CitationStylesStyle = None
    formatter = None
    CiteProcJSON = None

try:
    from citeproc_styles import get_style_filepath, get_style_name
except ImportError:  # optional `citation` extra is not installed
    get_style_filepath = None
    get_style_name = None


class CitationEngineUnavailable(RuntimeError):
    """The optional CSL formatting engine is not installed."""


@dataclass(frozen=True)
class CitationStyleOption:
    key: str
    name: str


@dataclass(frozen=True)
class CitationStyleSelection:
    matches: tuple[CitationStyleOption, ...]
    included: CitationStyleOption | None


@lru_cache
def builtin_style_catalog() -> tuple[CitationStyleOption, ...]:
    if get_style_filepath is None:
        return ()
    try:
        import importlib.resources

        roots = (
            importlib.resources.files("citeproc_styles") / "styles",
            importlib.resources.files("citeproc_styles") / "styles" / "dependent",
        )
        options: dict[str, CitationStyleOption] = {}
        for root in roots:
            for resource in root.iterdir():
                if resource.name.endswith(".csl"):
                    key = resource.name.removesuffix(".csl")
                    name = key
                    if get_style_name is not None:
                        with suppress(Exception):
                            name = get_style_name(key)
                    options[key] = CitationStyleOption(key=key, name=name)
        return tuple(sorted(options.values(), key=lambda option: option.name.casefold()))
    except Exception:
        return ()


def select_builtin_citation_styles(
    query: str = "", limit: int = 50, include: str = ""
) -> CitationStyleSelection:
    """Filter CSL styles and resolve an explicitly included style from one catalog snapshot."""
    catalog = builtin_style_catalog()
    normalized_query = query.strip().casefold()
    matches = (
        option
        for option in catalog
        if not normalized_query
        or normalized_query in option.key.casefold()
        or normalized_query in option.name.casefold()
    )
    styles = tuple(list(matches)[: max(1, min(limit, 200))])
    normalized_include = include.strip().casefold()
    included = next(
        (
            option
            for option in catalog
            if normalized_include and option.key.casefold() == normalized_include
        ),
        None,
    )
    if included is not None and any(option.key == included.key for option in styles):
        included = None
    return CitationStyleSelection(matches=styles, included=included)


def builtin_style_xml(style_key: str) -> str | None:
    """Return the CSL XML for a built-in style, or None if unavailable."""
    if get_style_filepath is None:
        return None
    try:
        path = get_style_filepath(style_key)
    except Exception:
        return None
    return Path(path).read_text(encoding="utf-8")


def _load_style(xml_text: str) -> Any:
    if CitationStylesStyle is None:
        raise CitationEngineUnavailable("CSL formatting requires the 'citation' extra")
    return CitationStylesStyle(io.BytesIO(xml_text.encode("utf-8")))


def is_valid_csl(xml_text: str) -> bool:
    """Return True when the text parses as a CSL style."""
    if not xml_text.strip():
        return False
    try:
        _load_style(xml_text)
    except Exception:
        return False
    return True
