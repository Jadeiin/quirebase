"""Library-owned bibliographic inputs and pure persistence value conversion."""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from inquiro.bibliography import REFERENCE_TYPE_TO_BIBTEX, extract_year
from inquiro.canonical import clean_markup, clean_rich_markup, normalize_reference_type
from inquiro.identifiers import normalize_doi

from quirebase.core.errors import ValidationFailure
from quirebase.models import normalize_author_identity

from .authors import parse_author_list_string, parse_author_name

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from quirebase.models import Item, ItemAuthor, ItemIdentifier

STOP_WORDS = {
    "a",
    "an",
    "the",
    "in",
    "on",
    "of",
    "for",
    "with",
    "and",
    "or",
    "to",
    "at",
    "by",
    "from",
}

_BOUNDED_METADATA_FIELDS = {
    "publication_date": 32,
    "volume": 100,
    "issue": 100,
    "pages": 100,
    "place_published": 255,
}


def _bounded_text(value: str, field: str, limit: int) -> str:
    if len(value) > limit:
        raise ValidationFailure(f"{field} is too long")
    return value


def clean_identifier_value(provider: str, value: str) -> str:
    cleaned = value.strip()
    if provider.lower() == "doi":
        cleaned = normalize_doi(cleaned).rstrip(".,; ")
    return cleaned


type JsonValue = str | int | float | bool | tuple[JsonValue, ...] | Mapping[str, JsonValue] | None


@dataclass(frozen=True)
class Contributor:
    last_name: str
    first_name: str | None = None
    is_corresponding: bool = False


@dataclass(frozen=True)
class ExternalIdentifier:
    provider: str
    value: str


@dataclass(frozen=True)
class CustomField:
    name: str
    value: JsonValue


@dataclass(frozen=True)
class ItemMetadata:
    title: str
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    publication_date: str | None = None
    publication_title: str | None = None
    reference_type: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    affiliation: str | None = None
    publisher: str | None = None
    place_published: str | None = None
    journal_abbreviation: str | None = None
    bibtex_key: str | None = None
    bibtex_type: str | None = None
    urls: tuple[str, ...] = ()
    authors: tuple[Contributor, ...] = ()
    editors: tuple[Contributor, ...] = ()
    doi: str | None = None
    identifiers: tuple[ExternalIdentifier, ...] = ()
    custom_fields: tuple[CustomField, ...] = ()


@dataclass(frozen=True)
class ItemWriteResult:
    item_id: UUID
    version: int


def _stored_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return tuple(_stored_json_value(entry) for entry in value)
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _stored_json_value(entry) for key, entry in value.items()}
    raise ValidationFailure("stored custom fields contain an unsupported value")


def metadata_from_item(
    item: Item,
    authors: Sequence[ItemAuthor],
    editors: Sequence[ItemAuthor],
    identifiers: Sequence[ItemIdentifier],
) -> ItemMetadata:
    """Project persisted Item metadata into the same shape accepted by replacement writes."""
    custom_fields: tuple[CustomField, ...] = ()
    if item.custom_fields:
        parsed_custom_fields = item.custom_fields
        if not isinstance(parsed_custom_fields, dict):
            raise ValidationFailure("stored custom fields must be a JSON object")
        custom_fields = tuple(
            CustomField(str(name), _stored_json_value(value))
            for name, value in parsed_custom_fields.items()
        )

    def contributors(links: Sequence[ItemAuthor]) -> tuple[Contributor, ...]:
        return tuple(
            Contributor(
                last_name=link.author.last_name,
                first_name=link.author.first_name,
                is_corresponding=link.is_corresponding,
            )
            for link in links
        )

    return ItemMetadata(
        title=item.title,
        abstract=item.abstract,
        keywords=tuple(
            value.strip() for value in (item.keywords or "").split(";") if value.strip()
        ),
        publication_date=item.publication_date,
        publication_title=item.publication_title,
        reference_type=item.reference_type,
        volume=item.volume,
        issue=item.issue,
        pages=item.pages,
        affiliation=item.affiliation,
        publisher=item.publisher,
        place_published=item.place_published,
        journal_abbreviation=item.journal_abbreviation,
        bibtex_key=item.bibtex_id,
        bibtex_type=item.bibtex_type,
        urls=tuple(value.strip() for value in (item.urls or "").splitlines() if value.strip()),
        authors=contributors(authors),
        editors=contributors(editors),
        doi=item.doi,
        identifiers=tuple(ExternalIdentifier(row.provider, row.value) for row in identifiers),
        custom_fields=custom_fields,
    )


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _bounded_optional_text(value: str | None, field: str, limit: int) -> str | None:
    normalized = _optional_text(value)
    return _bounded_text(normalized, field, limit) if normalized is not None else None


def _bibliographic_values(metadata: ItemMetadata) -> dict[str, object]:
    title = metadata.title.strip()
    if not title:
        raise ValidationFailure("title is required")
    reference_type = normalize_reference_type(metadata.reference_type or "")
    return {
        "title": title,
        "abstract": _optional_text(metadata.abstract),
        "keywords": "; ".join(value.strip() for value in metadata.keywords if value.strip())
        or None,
        "publication_date": _bounded_optional_text(
            metadata.publication_date, "publication date", 32
        ),
        "publication_title": _optional_text(metadata.publication_title),
        "reference_type": _bounded_optional_text(reference_type, "reference type", 40),
        "volume": _bounded_optional_text(metadata.volume, "volume", 100),
        "issue": _bounded_optional_text(metadata.issue, "issue", 100),
        "pages": _bounded_optional_text(metadata.pages, "pages", 100),
        "affiliation": _optional_text(metadata.affiliation),
        "publisher": _optional_text(metadata.publisher),
        "place_published": _bounded_optional_text(metadata.place_published, "place published", 255),
        "journal_abbreviation": _optional_text(metadata.journal_abbreviation),
        "bibtex_id": _bounded_optional_text(metadata.bibtex_key, "BibTeX key", 255),
        "bibtex_type": _bounded_optional_text(metadata.bibtex_type, "BibTeX type", 40),
        "urls": "\n".join(value.strip() for value in metadata.urls if value.strip()) or None,
    }


def _identifier_pairs(metadata: ItemMetadata) -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for identifier in metadata.identifiers:
        provider = identifier.provider.strip().lower()
        if not provider or provider == "doi":
            continue
        value = clean_identifier_value(provider, identifier.value)
        if value:
            pairs[provider] = value
    if metadata.doi and (doi := clean_identifier_value("doi", metadata.doi)):
        pairs["doi"] = doi
    return list(pairs.items())


def _contributor_payload(contributors: tuple[Contributor, ...], *, editor: bool) -> list[dict]:
    payload: list[dict] = []
    seen: set[str] = set()
    for contributor in contributors:
        last_name = contributor.last_name.strip()
        first_name = _optional_text(contributor.first_name)
        if not last_name:
            raise ValidationFailure("contributor last name is required")
        if editor and contributor.is_corresponding:
            raise ValidationFailure("editors cannot be corresponding authors")
        identity = normalize_author_identity(last_name, first_name)
        if len(last_name) > 120 or (first_name is not None and len(first_name) > 120):
            raise ValidationFailure("contributor name is too long")
        if identity in seen:
            raise ValidationFailure("contributors must be unique within a role")
        seen.add(identity)
        payload.append({
            "last_name": last_name,
            "first_name": first_name,
            "is_corresponding": contributor.is_corresponding,
        })
    return payload


def _custom_field_values(fields: tuple[CustomField, ...]) -> dict | None:
    values: dict[str, JsonValue] = {}
    for custom_field in fields:
        name = custom_field.name.strip()
        if not name:
            raise ValidationFailure("custom field name is required")
        if name in values:
            raise ValidationFailure("custom field names must be unique")
        values[name] = custom_field.value
    return values or None


def generate_bibtex_key(item: Item) -> str:
    author_part = "Unknown"
    if item.authors:
        first_author = item.authors.split(";")[0].strip()
        last_name, _first_name = parse_author_name(first_author)
        # Clean non-alphanumeric
        last_clean = re.sub(r"[^A-Za-z0-9]", "", last_name)
        if last_clean:
            author_part = last_clean.capitalize()

    year_part = extract_year(item.publication_date) or "XXXX"

    title_part = "Work"
    if item.title:
        words = re.findall(r"[A-Za-z0-9]+", item.title)
        for word in words:
            if word.lower() not in STOP_WORDS and len(word) > 2:
                title_part = word.capitalize()
                break

    return f"{author_part}{year_part}{title_part}"


@dataclass(frozen=True)
class MetadataWrite:
    values: dict[str, object]
    authors: list[dict] | None = None
    editors: list[dict] | None = None
    identifiers: list[tuple[str, str]] | None = None


def metadata_write(metadata: ItemMetadata) -> MetadataWrite:
    return MetadataWrite(
        values=_bibliographic_values(metadata)
        | {"custom_fields": _custom_field_values(metadata.custom_fields)},
        authors=_contributor_payload(metadata.authors, editor=False),
        editors=_contributor_payload(metadata.editors, editor=True),
        identifiers=_identifier_pairs(metadata),
    )


def candidate_write(
    item: Item,
    record: dict,
    *,
    merge: bool,
    existing_identifiers: dict[str, str],
    forced_identifiers: dict[str, str] | None = None,
) -> MetadataWrite:
    """Convert a Provider/import candidate while retaining its explicit merge semantics."""
    values: dict[str, object] = {}
    scalar_fields = {
        "title": clean_rich_markup,
        "abstract": clean_rich_markup,
        "publication_date": lambda value: str(value).strip(),
        "publication_title": clean_markup,
        "journal_abbreviation": clean_markup,
        "volume": lambda value: str(value).strip(),
        "issue": lambda value: str(value).strip(),
        "pages": lambda value: str(value).strip(),
        "publisher": clean_markup,
        "affiliation": clean_markup,
        "place_published": clean_markup,
    }
    for field, transform in scalar_fields.items():
        raw = record.get(field)
        if raw and (value := transform(raw)):
            if (limit := _BOUNDED_METADATA_FIELDS.get(field)) is not None:
                value = _bounded_text(str(value), field, limit)
            values[field] = value
    if record.get("reference_type") and (
        ref_type := normalize_reference_type(record["reference_type"])
    ):
        values["reference_type"] = _bounded_text(ref_type, "reference type", 40)
        bib_type = record.get("bibtex_type") or REFERENCE_TYPE_TO_BIBTEX.get(ref_type, ref_type)
        if bib_type:
            values["bibtex_type"] = _bounded_text(str(bib_type).strip().lower(), "BibTeX type", 40)
    elif record.get("bibtex_type"):
        values["bibtex_type"] = _bounded_text(
            str(record["bibtex_type"]).strip().lower(), "BibTeX type", 40
        )

    urls = (
        [value.strip() for value in (item.urls or "").splitlines() if value.strip()]
        if merge
        else []
    )
    keywords = (
        [value.strip() for value in (item.keywords or "").split(";") if value.strip()]
        if merge
        else []
    )
    for url in str(record.get("urls") or "").splitlines():
        url = url.strip()
        if url and url not in urls:
            urls.append(url)
    for keyword in str(record.get("keywords") or "").split(";"):
        keyword = keyword.strip()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    if record.get("urls") or not merge:
        values["urls"] = "\n".join(urls) or None
    if record.get("keywords") or not merge:
        values["keywords"] = "; ".join(keywords) or None
    custom_fields = record.get("custom_fields")
    if custom_fields is not None:
        if not isinstance(custom_fields, dict):
            raise ValidationFailure("custom fields must be a JSON object")
        values["custom_fields"] = dict(custom_fields)
    if not item.bibtex_id and (key := str(record.get("bibtex_id") or "").strip()):
        values["bibtex_id"] = _bounded_text(key, "BibTeX key", 255)

    identifiers = dict(existing_identifiers) if merge else {}
    if merge and item.doi:
        identifiers["doi"] = item.doi
    raw_identifiers = record.get("identifiers")
    if raw_identifiers:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = (
                json.loads(raw_identifiers) if isinstance(raw_identifiers, str) else raw_identifiers
            )
            if isinstance(parsed, dict):
                for provider, value in parsed.items():
                    if isinstance(value, str) and value.strip():
                        identifiers[provider] = clean_identifier_value(provider, value)
    if record.get("doi") and (doi := clean_identifier_value("doi", record["doi"])):
        identifiers["doi"] = doi
    for provider, value in (forced_identifiers or {}).items():
        if cleaned := clean_identifier_value(provider, value):
            identifiers[provider] = cleaned
    return MetadataWrite(
        values=values,
        authors=parse_author_list_string(str(record["authors"])) if record.get("authors") else None,
        editors=parse_author_list_string(str(record["editors"])) if record.get("editors") else None,
        identifiers=list(identifiers.items()) if identifiers else None,
    )
