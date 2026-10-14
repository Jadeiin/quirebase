"""Neutral bibliographic records, bibliography interchange and Citation Key generation.

The package facade is the only supported import surface; internal modules are private
implementation seams (see ``tests/test_architecture.py``).
"""

from __future__ import annotations

from inquiro.bibliography.engine import (
    render_bibliography,
    render_citation,
    work_to_csl_json,
)
from inquiro.bibliography.formats import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    SUPPORTED_FORMATS,
    export_bibliography_records,
    parse_bibliography_records,
)
from inquiro.bibliography.keys import (
    DEFAULT_CITATION_KEY_FORMULA,
    CitationKeyFormulaError,
    citation_key_suffix,
    evaluate_citation_key_formula,
    extract_year,
    generate_default_citation_key,
    preview_citation_key,
    suffixed_citation_key,
)
from inquiro.bibliography.options import (
    BibliographyExportOptions,
    InvalidExportOptions,
)
from inquiro.bibliography.styles import (
    CitationStyleOption,
    CitationStyleSelection,
    builtin_style_catalog,
    builtin_style_xml,
    is_valid_csl,
    select_builtin_citation_styles,
)

__all__ = [
    "BIBLIOGRAPHY_EXTENSIONS",
    "BIBLIOGRAPHY_MEDIA_TYPES",
    "DEFAULT_CITATION_KEY_FORMULA",
    "SUPPORTED_FORMATS",
    "BibliographyExportOptions",
    "CitationKeyFormulaError",
    "CitationStyleOption",
    "CitationStyleSelection",
    "InvalidExportOptions",
    "builtin_style_catalog",
    "builtin_style_xml",
    "citation_key_suffix",
    "evaluate_citation_key_formula",
    "export_bibliography_records",
    "extract_year",
    "generate_default_citation_key",
    "is_valid_csl",
    "parse_bibliography_records",
    "preview_citation_key",
    "render_bibliography",
    "render_citation",
    "select_builtin_citation_styles",
    "suffixed_citation_key",
    "work_to_csl_json",
]
