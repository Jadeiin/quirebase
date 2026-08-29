"""Neutral bibliographic records, bibliography interchange and Citation Key generation.

The package facade is the only supported import surface; internal modules are private
implementation seams (see ``tests/test_architecture.py``).
"""

from __future__ import annotations

from inquiro.bibliography.engine import (
    REFERENCE_TYPE_TO_CSL,
    record_to_csl_json,
    render_bibliography,
    render_citation,
)
from inquiro.bibliography.formats import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    REFERENCE_TYPE_TO_BIBTEX,
    SUPPORTED_FORMATS,
    export_bibliography_records,
    first_url,
    parse_bibliography_records,
)
from inquiro.bibliography.keys import (
    DEFAULT_CITATION_KEY_FORMULA,
    CitationKeyFormulaError,
    citation_key_suffix,
    evaluate_citation_key_formula,
    extract_year,
    preview_citation_key,
    suffixed_citation_key,
)
from inquiro.bibliography.options import (
    BibliographyExportOptions,
    InvalidExportOptions,
)
from inquiro.bibliography.records import (
    BibliographyRecord,
    Contributor,
    record_from_item,
)
from inquiro.bibliography.styles import (
    CitationEngineUnavailable,
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
    "REFERENCE_TYPE_TO_BIBTEX",
    "REFERENCE_TYPE_TO_CSL",
    "SUPPORTED_FORMATS",
    "BibliographyExportOptions",
    "BibliographyRecord",
    "CitationEngineUnavailable",
    "CitationKeyFormulaError",
    "CitationStyleOption",
    "CitationStyleSelection",
    "Contributor",
    "InvalidExportOptions",
    "builtin_style_catalog",
    "builtin_style_xml",
    "citation_key_suffix",
    "evaluate_citation_key_formula",
    "export_bibliography_records",
    "extract_year",
    "first_url",
    "is_valid_csl",
    "parse_bibliography_records",
    "preview_citation_key",
    "record_from_item",
    "record_to_csl_json",
    "render_bibliography",
    "render_citation",
    "select_builtin_citation_styles",
    "suffixed_citation_key",
]
