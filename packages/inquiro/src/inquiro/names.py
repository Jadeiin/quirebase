"""Shared bibliographic name values and name parsing."""

from __future__ import annotations

from dataclasses import dataclass

from bibtexparser.middlewares.names import parse_single_name_into_parts as _parse_single_name

from inquiro.richtext import convert_rich_text


def _corporate_family(value: str) -> str | None:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped.startswith("{") and stripped.endswith("}"):
        return stripped[1:-1].strip()
    return None


def _latex_decode(value: str) -> str:
    return convert_rich_text(value, source="latex", target="text")


@dataclass(frozen=True)
class ContributorName:
    """A two-part contributor, with a nullable given name representing a literal name."""

    family_name: str
    given_name: str | None = None

    @classmethod
    def parse(cls, value: str) -> ContributorName:
        parts = _parse_single_name(value)
        first = " ".join(parts.first).strip()
        if first in {"{}", "{ }"}:
            first = ""
        family = " ".join(parts.von + parts.last + parts.jr).strip() or value.strip()
        literal_family = _corporate_family(value)
        if literal_family is not None:
            return cls(family_name=_latex_decode(literal_family))
        return cls(
            family_name=_latex_decode(family),
            given_name=_latex_decode(first) or None,
        )

    @property
    def literal(self) -> bool:
        return self.given_name is None

    def display_name(self) -> str:
        return f"{self.family_name}, {self.given_name}" if self.given_name else self.family_name

    def storage_name(self) -> str:
        """Serialize a Contributor so a BibTeX name parser reads it back intact."""
        if self.literal:
            return f"{{{self.family_name}}}"
        return f"{self.family_name}, {self.given_name}"
