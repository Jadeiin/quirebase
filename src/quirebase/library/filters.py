from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from quirebase.core.errors import ValidationFailure

if TYPE_CHECKING:
    from uuid import UUID


@dataclass(frozen=True)
class AuthorFilter:
    last_name: str
    first_name: str | None = None


@dataclass(frozen=True)
class LibraryFilter:
    q: str = ""
    tag: UUID | None = None
    project: UUID | None = None
    year: str = ""
    keyword: str = ""
    author: str = ""
    author_orcid: str | None = None
    author_ror: str | None = None
    has_files: bool | None = None
    has_tags: bool | None = None
    has_projects: bool | None = None
    reference_type: str | None = None
    keyword_exact: str | None = None
    authors: tuple[AuthorFilter, ...] = ()
    publication_title: str | None = None
    import_batch: UUID | None = None

    def __post_init__(self) -> None:
        if self.author_orcid is not None:
            object.__setattr__(self, "author_orcid", _orcid_uri(self.author_orcid))
        if self.author_ror is not None:
            object.__setattr__(self, "author_ror", _ror_uri(self.author_ror))


def _ror_uri(value: str) -> str:
    match = re.fullmatch(
        r"(?:https?://ror\.org/)?(0[0-9a-hjkmnp-tv-z]{6}[0-9]{2})/?",
        value.strip(),
        flags=re.IGNORECASE | re.ASCII,
    )
    if match is None:
        raise ValidationFailure("invalid author institution ROR")
    identifier = match[1].lower()
    number = 0
    for character in identifier[:7]:
        number = number * 32 + "0123456789abcdefghjkmnpqrstvwxyz".index(character)
    if int(identifier[-2:]) != 98 - (number * 100 % 97):
        raise ValidationFailure("invalid author institution ROR")
    return f"https://ror.org/{identifier}"


def _orcid_uri(value: str) -> str:
    match = re.fullmatch(
        r"(?:https?://orcid\.org/)?([0-9]{4}-[0-9]{4}-[0-9]{4}-[0-9]{3}[0-9X])/?",
        value.strip(),
        flags=re.IGNORECASE | re.ASCII,
    )
    if match is None:
        raise ValidationFailure("invalid author ORCID")
    identifier = match[1].upper()
    digits = identifier.replace("-", "")
    total = 0
    for digit in digits[:-1]:
        total = (total + int(digit)) * 2
    checksum = (12 - total % 11) % 11
    if digits[-1] != ("X" if checksum == 10 else str(checksum)):
        raise ValidationFailure("invalid author ORCID")
    return f"https://orcid.org/{identifier}"
