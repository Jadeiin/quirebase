"""The one export options object and its validation."""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_CITATION_KEY_FORMULA = "auth.capitalize + year + shorttitle(1).capitalize"


class InvalidExportOptions(ValueError):
    """An export option value is outside its allowed enumeration or shape."""


@dataclass(frozen=True)
class BibliographyExportOptions:
    include_abstract: bool = True
    preserve_case: bool = False
    encoding: str = "unicode"
    doi_policy: str = "include"
    url_policy: str = "include"
    excluded_fields: tuple[str, ...] = ()
    sort_by: str = "input"
    citation_key_formula: str = DEFAULT_CITATION_KEY_FORMULA
    citation_key_force_ascii: bool = False

    def validated(self, *, file_format: str | None = None) -> BibliographyExportOptions:
        if self.encoding not in {"unicode", "latex"}:
            raise InvalidExportOptions("encoding must be unicode or latex")
        if self.doi_policy not in {"include", "omit"}:
            raise InvalidExportOptions("unknown DOI policy")
        if self.url_policy not in {"include", "omit", "omit_when_doi"}:
            raise InvalidExportOptions("unknown URL policy")
        if self.sort_by not in {"input", "citation_key", "author", "year", "title"}:
            raise InvalidExportOptions("unknown bibliography sort order")
        if len(self.excluded_fields) > 100 or any(
            not isinstance(field, str)
            or len(field) > 80
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", field)
            for field in self.excluded_fields
        ):
            raise InvalidExportOptions("invalid excluded bibliography fields")
        if self.excluded_fields and file_format is not None:
            if file_format not in {"bibtex", "csl-json"}:
                raise InvalidExportOptions(
                    "field exclusions are supported only for BibTeX and CSL-JSON"
                )
            required = {"id", "entrytype" if file_format == "bibtex" else "type"}
            if required.intersection(field.casefold() for field in self.excluded_fields):
                raise InvalidExportOptions(
                    "cannot exclude required bibliography identity/type fields"
                )
        if len(self.citation_key_formula) > 1000:
            raise InvalidExportOptions("citation key formula is too long")
        return self

    def includes_url(self, *, has_doi: bool) -> bool:
        return self.url_policy == "include" or (self.url_policy == "omit_when_doi" and not has_doi)
