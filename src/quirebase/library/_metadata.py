"""Library-owned bibliographic inputs and pure persistence value conversion."""

from __future__ import annotations

import contextlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from inquiro.bibliography import extract_year
from inquiro.canonical import clean_markup, clean_rich_markup
from inquiro.identifiers import normalize_doi, parse_arxiv, parse_openalex
from inquiro.reference_types import normalize_reference_type
from inquiro.richtext import convert_rich_text

from quirebase.core.errors import ValidationFailure
from quirebase.models import MAX_CITATION_KEY_LENGTH, ReferenceType, normalize_author_identity

from .authors import parse_author_name

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

MAX_TITLE_TEXT_LENGTH = 1000

_BOUNDED_METADATA_FIELDS = {
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
    provider = provider.strip().lower()
    if provider == "doi":
        cleaned = normalize_doi(cleaned).rstrip(".,; ")
    elif provider in {"arxiv", "openalex"}:
        parser = parse_arxiv if provider == "arxiv" else parse_openalex
        if identifier := parser(cleaned, provider):
            cleaned = identifier.value
    return cleaned


def normalize_identifier_pairs(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    normalized: dict[str, str] = {}
    for provider, value in pairs:
        provider = provider.strip().lower()
        value = clean_identifier_value(provider, value)
        if not provider or not value:
            continue
        _bounded_text(provider, "identifier provider", 40)
        _bounded_text(value, "identifier value", 500)
        if provider in normalized:
            raise ValidationFailure("only one identifier per provider is allowed")
        normalized[provider] = value
    return list(normalized.items())


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
    reference_type: ReferenceType = ReferenceType.document
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    affiliation: str | None = None
    publisher: str | None = None
    place_published: str | None = None
    journal_abbreviation: str | None = None
    citation_key: str | None = None
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
        citation_key=item.citation_key,
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


def _validated_title(value: str) -> str:
    title = value.strip()
    plain = convert_rich_text(title, source="html", target="text").strip()
    if not plain:
        raise ValidationFailure("title is required")
    _bounded_text(plain, "title", MAX_TITLE_TEXT_LENGTH)
    return title


def _validated_publication_date(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", normalized):
        raise ValidationFailure("publication date must use YYYY, YYYY-MM or YYYY-MM-DD")
    parts = [int(part) for part in normalized.split("-")]
    try:
        date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError as error:
        raise ValidationFailure("publication date is invalid") from error
    return normalized


def _bibliographic_values(metadata: ItemMetadata) -> dict[str, object]:
    try:
        reference_type = ReferenceType(metadata.reference_type)
    except ValueError as error:
        raise ValidationFailure("reference type must be a supported literature type") from error
    return {
        "title": _validated_title(metadata.title),
        "abstract": _optional_text(metadata.abstract),
        "keywords": "; ".join(value.strip() for value in metadata.keywords if value.strip())
        or None,
        "publication_date": _validated_publication_date(metadata.publication_date),
        "publication_title": _optional_text(metadata.publication_title),
        "reference_type": reference_type,
        "volume": _bounded_optional_text(metadata.volume, "volume", 100),
        "issue": _bounded_optional_text(metadata.issue, "issue", 100),
        "pages": _bounded_optional_text(metadata.pages, "pages", 100),
        "affiliation": _optional_text(metadata.affiliation),
        "publisher": _optional_text(metadata.publisher),
        "place_published": _bounded_optional_text(metadata.place_published, "place published", 255),
        "journal_abbreviation": _optional_text(metadata.journal_abbreviation),
        "citation_key": _bounded_optional_text(
            metadata.citation_key, "Citation key", MAX_CITATION_KEY_LENGTH
        ),
        "urls": "\n".join(value.strip() for value in metadata.urls if value.strip()) or None,
    }


def _identifier_pairs(metadata: ItemMetadata) -> list[tuple[str, str]]:
    pairs = [
        (identifier.provider, identifier.value)
        for identifier in metadata.identifiers
        if identifier.provider.strip().lower() != "doi"
    ]
    if metadata.doi:
        pairs.append(("doi", metadata.doi))
    return normalize_identifier_pairs(pairs)


def _contributor_payload(contributors: tuple[Contributor, ...], *, editor: bool) -> list[dict]:
    payload: list[dict] = []
    seen: set[str] = set()
    for contributor in contributors:
        last_name = " ".join(contributor.last_name.split())
        first_name = (
            " ".join(contributor.first_name.split()) or None if contributor.first_name else None
        )
        if not last_name:
            raise ValidationFailure("contributor last name is required")
        if editor and contributor.is_corresponding:
            raise ValidationFailure("editors cannot be corresponding authors")
        identity = normalize_author_identity(last_name, first_name)
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


def generate_citation_key(item: Item) -> str:
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
        plain_title = convert_rich_text(item.title, source="html", target="text")
        words = re.findall(r"[A-Za-z0-9]+", plain_title)
        for word in words:
            if word.lower() not in STOP_WORDS and len(word) > 2:
                title_part = word.capitalize()
                break

    # Reserve room for both the year and title even when the family name is long.
    author_part = author_part[: MAX_CITATION_KEY_LENGTH // 2]
    title_part = title_part[: MAX_CITATION_KEY_LENGTH - len(author_part) - len(year_part)]
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
) -> MetadataWrite:
    """Convert a Provider/import candidate while retaining its explicit merge semantics."""
    values: dict[str, object] = {}
    scalar_fields = {
        "title": clean_rich_markup,
        "abstract": clean_rich_markup,
        "publication_date": _validated_publication_date,
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
            if field == "title":
                value = _validated_title(str(value))
            if (limit := _BOUNDED_METADATA_FIELDS.get(field)) is not None:
                value = _bounded_text(str(value), field, limit)
            values[field] = value
    if record.get("reference_type") and (
        ref_type := normalize_reference_type(record["reference_type"])
    ):
        values["reference_type"] = ReferenceType(ref_type)

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
    incoming_urls = record.get("urls")
    if incoming_urls is not None and not isinstance(incoming_urls, (list, tuple)):
        raise ValidationFailure("candidate URLs must be structured links")
    for link in incoming_urls or ():
        if not isinstance(link, dict) or not isinstance(link.get("url"), str):
            raise ValidationFailure("candidate URL is invalid")
        url = link["url"].strip()
        if url and url not in urls:
            urls.append(url)
    incoming_keywords = record.get("keywords")
    if incoming_keywords is not None and not isinstance(incoming_keywords, (list, tuple)):
        raise ValidationFailure("candidate keywords must be a list")
    for keyword in incoming_keywords or ():
        if not isinstance(keyword, str):
            raise ValidationFailure("candidate keyword is invalid")
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
    if not item.citation_key and (key := str(record.get("citation_key") or "").strip()):
        values["citation_key"] = _bounded_text(key, "Citation key", MAX_CITATION_KEY_LENGTH)

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
                identifiers.update(
                    normalize_identifier_pairs([
                        (provider, value)
                        for provider, value in parsed.items()
                        if isinstance(value, str) and value.strip()
                    ])
                )
    if record.get("doi") and (doi := clean_identifier_value("doi", record["doi"])):
        identifiers["doi"] = doi

    def contributors(role: str) -> list[dict] | None:
        entries = record.get(role)
        if entries is None:
            return None
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValidationFailure("candidate contributors must be structured names")
        payload = _contributor_payload(
            tuple(
                Contributor(
                    last_name=entry.get("last_name", ""),
                    first_name=entry.get("first_name"),
                    is_corresponding=bool(entry.get("is_corresponding")),
                )
                for entry in entries
            ),
            editor=role == "editors",
        )
        for entry, contributor in zip(entries, payload, strict=True):
            if entry.get("is_corresponding") is None:
                contributor["is_corresponding"] = None
        return payload

    return MetadataWrite(
        values=values,
        authors=contributors("authors"),
        editors=contributors("editors"),
        identifiers=list(identifiers.items()) if identifiers else None,
    )
