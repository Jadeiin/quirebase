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
    include_identifiers: bool = False
    include_custom_fields: bool = False
    encoding: str = "unicode"
    journal_mode: str = "full"
    doi_policy: str = "include"
    url_policy: str = "include"
    excluded_fields: tuple[str, ...] = ()
    sort_by: str = "input"
    citation_key_formula: str = DEFAULT_CITATION_KEY_FORMULA
    citation_key_force_ascii: bool = False

    def validated(self) -> BibliographyExportOptions:
        """Validate every enumeration and shape constraint.

        Raises :class:`InvalidExportOptions` for any field outside its allowed
        values; this is the single validation point shared by every caller.
        """
        if self.encoding not in {"unicode", "latex"}:
            raise InvalidExportOptions("encoding must be unicode or latex")
        if self.journal_mode not in {"full", "abbreviated", "prefer_abbreviated"}:
            raise InvalidExportOptions("unknown journal mode")
        if self.doi_policy not in {"include", "omit"}:
            raise InvalidExportOptions("unknown DOI policy")
        if self.url_policy not in {"include", "omit", "omit_when_doi"}:
            raise InvalidExportOptions("unknown URL policy")
        if self.sort_by not in {"input", "citation_key", "author", "year", "title"}:
            raise InvalidExportOptions("unknown bibliography sort order")
        if len(self.excluded_fields) > 100 or any(
            len(field) > 80 or not re.fullmatch(r"[A-Za-z0-9_]+", field)
            for field in self.excluded_fields
        ):
            raise InvalidExportOptions("invalid excluded bibliography fields")
        if len(self.citation_key_formula) > 1000:
            raise InvalidExportOptions("citation key formula is too long")
        return self
