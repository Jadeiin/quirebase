"""Neutral bibliographic snapshots, validation and source merge rules.

No database, authorization or application object is accepted by this module.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, replace
from datetime import date
from typing import TYPE_CHECKING, Any

from inquiro.canonical import clean_markup, clean_rich_markup
from inquiro.identifiers import canonical_doi, parse_arxiv, parse_isbn, parse_openalex
from inquiro.models import (
    Affiliation,
    BibliographicMetadata,
    CandidateRecord,
    Contributor,
    CustomField,
    Identifier,
    JsonValue,
    ResourceLink,
)
from inquiro.reference_types import ReferenceType, normalize_reference_type
from inquiro.richtext import convert_rich_text


class MetadataValidationError(ValueError):
    """A bibliographic snapshot has invalid or ambiguous values."""


if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.bibliography import BibliographyRecord


def clean_identifier_value(provider: str, value: str) -> str:
    if not isinstance(provider, str) or not isinstance(value, str):
        raise MetadataValidationError("identifier provider and value must be text")
    cleaned = value.strip()
    provider = provider.strip().lower()
    if provider == "doi":
        cleaned = canonical_doi(cleaned).rstrip(".,; ")
    elif provider in {"arxiv", "isbn", "openalex"}:
        parser = {"arxiv": parse_arxiv, "isbn": parse_isbn, "openalex": parse_openalex}[provider]
        if identifier := parser(cleaned, provider):
            cleaned = identifier.value
    return cleaned


def normalize_identifier_pairs(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    normalized: dict[str, str] = {}
    for provider, value in pairs:
        if not isinstance(provider, str):
            raise MetadataValidationError("identifier provider and value must be text")
        provider = provider.strip().lower()
        value = clean_identifier_value(provider, value)
        if not provider or not value:
            continue
        if provider in normalized:
            raise MetadataValidationError("only one identifier per provider is allowed")
        normalized[provider] = value
    return list(normalized.items())


def _stored_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return tuple(_stored_json_value(entry) for entry in value)
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {str(key): _stored_json_value(entry) for key, entry in value.items()}
    raise MetadataValidationError("stored custom fields contain an unsupported value")


def _optional_text(value: str | None) -> str | None:
    if value is not None and not isinstance(value, str):
        raise MetadataValidationError("metadata text fields must be text")
    return value.strip() or None if value else None


def _validated_title(value: str) -> str:
    if not isinstance(value, str):
        raise MetadataValidationError("title must be text")
    title = value.strip()
    plain = convert_rich_text(title, source="html", target="text").strip()
    if not plain:
        raise MetadataValidationError("title is required")
    return title


def _validated_publication_date(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    if not re.fullmatch(r"\d{4}(?:-\d{2}(?:-\d{2})?)?", normalized):
        raise MetadataValidationError("publication date must use YYYY, YYYY-MM or YYYY-MM-DD")
    parts = [int(part) for part in normalized.split("-")]
    try:
        date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)
    except ValueError as error:
        raise MetadataValidationError("publication date is invalid") from error
    return normalized


def _bibliographic_values(metadata: BibliographicMetadata) -> dict[str, object]:
    try:
        reference_type = ReferenceType(metadata.reference_type)
    except ValueError as error:
        raise MetadataValidationError(
            "reference type must be a supported literature type"
        ) from error
    return {
        "title": _validated_title(metadata.title),
        "abstract": _optional_text(metadata.abstract),
        "keywords": list(
            dict.fromkeys(value.strip() for value in metadata.keywords if value.strip())
        ),
        "publication_date": _validated_publication_date(metadata.publication_date),
        "publication_title": _optional_text(metadata.publication_title),
        "reference_type": reference_type,
        "volume": _optional_text(metadata.volume),
        "issue": _optional_text(metadata.issue),
        "pages": _optional_text(metadata.pages),
        "publisher": _optional_text(metadata.publisher),
        "place_published": _optional_text(metadata.place_published),
        "journal_abbreviation": _optional_text(metadata.journal_abbreviation),
        "citation_key": _optional_text(metadata.citation_key),
        "urls": _link_payloads(metadata.urls),
    }


def _identifier_pairs(metadata: BibliographicMetadata) -> list[tuple[str, str]]:
    return _input_identifier_pairs(
        [(identifier.provider, identifier.value) for identifier in metadata.identifiers],
        metadata.doi,
    )


def _input_identifier_pairs(
    pairs: Sequence[tuple[str, str]], doi: str | None
) -> list[tuple[str, str]]:
    identifiers = dict(normalize_identifier_pairs(pairs))
    if doi:
        value = clean_identifier_value("doi", doi)
        if "doi" in identifiers and identifiers["doi"] != value:
            raise MetadataValidationError("doi conflicts with identifiers")
        if value:
            identifiers["doi"] = value
    return list(identifiers.items())


def _contributor_key(value: Contributor) -> tuple[str, str]:
    name = value.bibliographic_name
    return (
        " ".join(name.family_name.split()).casefold(),
        " ".join((name.given_name or "").split()).casefold(),
    )


def _name_part(value: str | None) -> str | None:
    return " ".join(value.split()) or None if value else None


def _contributor_payload(contributors: tuple[Contributor, ...], *, editor: bool) -> list[dict]:
    payload: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for contributor in contributors:
        if not isinstance(contributor.display_name, str) or any(
            value is not None and not isinstance(value, str)
            for value in (contributor.family_name, contributor.given_name, contributor.suffix)
        ):
            raise MetadataValidationError("contributor names must be text")
        name = " ".join(contributor.display_name.split())
        if not name:
            raise MetadataValidationError("contributor name is required")
        contributor = replace(
            contributor,
            display_name=name,
            family_name=_name_part(contributor.family_name),
            given_name=_name_part(contributor.given_name),
            suffix=_name_part(contributor.suffix),
        )
        if editor and contributor.is_corresponding:
            raise MetadataValidationError("editors cannot be corresponding authors")
        if contributor.is_corresponding is not None and not isinstance(
            contributor.is_corresponding, bool
        ):
            raise MetadataValidationError("corresponding status must be boolean or unknown")
        if contributor.kind not in {"person", "organization", "unknown"}:
            raise MetadataValidationError("contributor kind is invalid")
        identity = _contributor_key(contributor)
        if identity in seen:
            raise MetadataValidationError("contributors must be unique within a role")
        seen.add(identity)
        value = asdict(contributor)
        if contributor.suffix is None:
            value.pop("suffix")
        if contributor.kind == "unknown":
            value.pop("kind")
        if contributor.identifiers:
            value["identifiers"] = [
                asdict(row) for row in _identifier_objects(contributor.identifiers)
            ]
        else:
            value.pop("identifiers")
        if contributor.affiliations is not None:
            value["affiliations"] = [_affiliation_payload(row) for row in contributor.affiliations]
        else:
            value.pop("affiliations")
        payload.append(value)
    return payload


def _custom_field_values(fields: tuple[CustomField, ...]) -> dict | None:
    values: dict[str, JsonValue] = {}
    for custom_field in fields:
        name = custom_field.name.strip()
        if not name:
            raise MetadataValidationError("custom field name is required")
        if name in values:
            raise MetadataValidationError("custom field names must be unique")
        values[name] = _stored_json_value(custom_field.value)
    return values or None


@dataclass(frozen=True)
class MetadataUpdate:
    values: dict[str, object]
    identifiers: list[tuple[str, str]] | None = None


def metadata_values(metadata: BibliographicMetadata) -> MetadataUpdate:
    return MetadataUpdate(
        values=_bibliographic_values(metadata)
        | {
            "custom_fields": _custom_field_values(metadata.custom_fields),
            "authors": _contributor_payload(metadata.authors, editor=False),
            "editors": _contributor_payload(metadata.editors, editor=True),
        },
        identifiers=_identifier_pairs(metadata),
    )


def merge_metadata_values(
    item: BibliographicMetadata,
    record: dict,
    *,
    merge: bool,
) -> MetadataUpdate:
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
        "place_published": clean_markup,
    }
    for field, transform in scalar_fields.items():
        raw = record.get(field)
        if raw and (value := transform(raw)):
            if field == "title":
                value = _validated_title(str(value))
            values[field] = value
    if record.get("reference_type") and (
        ref_type := normalize_reference_type(record["reference_type"])
    ):
        values["reference_type"] = ReferenceType(ref_type)

    urls = [_link_payload(link) for link in item.urls] if merge else []
    keywords = list(item.keywords or ()) if merge else []
    incoming_urls = record.get("urls")
    if incoming_urls is not None and not isinstance(incoming_urls, (list, tuple)):
        raise MetadataValidationError("candidate URLs must be structured links")
    for link in incoming_urls or ():
        if not isinstance(link, dict) or not isinstance(link.get("url"), str):
            raise MetadataValidationError("candidate URL is invalid")
        normalized = _link_payload(ResourceLink(**link))
        previous = next((value for value in urls if value["url"] == normalized["url"]), None)
        if previous is None:
            urls.append(normalized)
        else:
            previous.update(normalized)
    incoming_keywords = record.get("keywords")
    if incoming_keywords is not None and not isinstance(incoming_keywords, (list, tuple)):
        raise MetadataValidationError("candidate keywords must be a list")
    for keyword in incoming_keywords or ():
        if not isinstance(keyword, str):
            raise MetadataValidationError("candidate keyword is invalid")
        keyword = keyword.strip()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    if record.get("urls") or not merge:
        values["urls"] = urls
    if record.get("keywords") or not merge:
        values["keywords"] = keywords
    custom_fields = record.get("custom_fields")
    if custom_fields is not None:
        if not isinstance(custom_fields, dict):
            raise MetadataValidationError("custom fields must be a JSON object")
        values["custom_fields"] = dict(custom_fields)
    if not item.citation_key and (key := str(record.get("citation_key") or "").strip()):
        values["citation_key"] = key

    identifiers = dict(_identifier_pairs(item)) if merge else {}
    raw_identifiers = record.get("identifiers")
    if raw_identifiers is not None and not isinstance(raw_identifiers, dict):
        raise MetadataValidationError("candidate identifiers must be a JSON object")
    identifiers.update(
        _input_identifier_pairs(list((raw_identifiers or {}).items()), record.get("doi"))
    )

    def contributors(role: str) -> list[dict] | None:
        entries = record.get(role)
        if entries is None:
            return None
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise MetadataValidationError("candidate contributors must be structured names")
        payload = _contributor_payload(
            tuple(_contributor_from_value(entry) for entry in entries),
            editor=role == "editors",
        )
        known = getattr(item, role)
        previous = {_contributor_key(row): row for row in known}
        for entry, contributor in zip(entries, payload, strict=True):
            incoming = _contributor_from_value(contributor)
            old = previous.get(_contributor_key(incoming))
            display_matches = []
            if incoming.kind == "unknown" and not incoming.family_name and not incoming.given_name:
                # Display-only credits may denote organizations. Prefer a unique
                # literal match, and never guess between credits with the same name.
                display_matches = [
                    row
                    for row in known
                    if " ".join(row.display_name.split()).casefold()
                    == incoming.display_name.casefold()
                    and (
                        incoming.suffix is None
                        or (_name_part(row.suffix) or "").casefold() == incoming.suffix.casefold()
                    )
                ]
                if display_matches:
                    old = display_matches[0] if len(display_matches) == 1 else None
            if old is None and incoming.suffix is None and len(display_matches) < 2:
                # A source may omit a known suffix. Only a unique match within
                # this role can inherit it; Smith Jr and Smith Sr stay separate.
                matches = [
                    row
                    for row in known
                    if _contributor_key(replace(row, suffix=None)) == _contributor_key(incoming)
                ]
                if len(matches) == 1:
                    old = matches[0]
            if old is not None:
                if (
                    role == "authors"
                    and entry.get("is_corresponding") is None
                    and old.is_corresponding is not None
                ):
                    contributor["is_corresponding"] = old.is_corresponding
                if entry.get("affiliations") is None and old.affiliations is not None:
                    contributor["affiliations"] = [
                        _affiliation_payload(value) for value in old.affiliations
                    ]
                if not entry.get("identifiers") and old.identifiers:
                    contributor["identifiers"] = [asdict(value) for value in old.identifiers]
                for field in ("family_name", "given_name", "kind", "suffix"):
                    if not entry.get(field) or (field == "kind" and entry[field] == "unknown"):
                        old_value = getattr(old, field)
                        if old_value and (field != "kind" or old_value != "unknown"):
                            contributor[field] = old_value
        return _contributor_payload(
            tuple(_contributor_from_value(value) for value in payload),
            editor=role == "editors",
        )

    for role in ("authors", "editors"):
        if (payload := contributors(role)) is not None:
            values[role] = payload
    return MetadataUpdate(
        values=values,
        identifiers=list(identifiers.items()) if identifiers else None,
    )


def _identifier_objects(values: object) -> tuple[Identifier, ...]:
    if not isinstance(values, (list, tuple)):
        raise MetadataValidationError("identifiers must be structured values")
    if any(not isinstance(value, Identifier | dict) for value in values):
        raise MetadataValidationError("identifiers must be structured values")
    try:
        result = tuple(
            value if isinstance(value, Identifier) else Identifier(**value) for value in values
        )
    except TypeError as error:
        raise MetadataValidationError("identifier provider and value are required") from error
    return tuple(
        Identifier(provider, value)
        for provider, value in normalize_identifier_pairs([
            (row.provider, row.value) for row in result
        ])
    )


def _affiliation_from_value(value: Affiliation | dict) -> Affiliation:
    if isinstance(value, Affiliation):
        return value
    if not isinstance(value, dict):
        raise MetadataValidationError("affiliation must be a structured value")
    try:
        return Affiliation(
            **(value | {"identifiers": _identifier_objects(value.get("identifiers", ()))})
        )
    except TypeError as error:
        raise MetadataValidationError(
            "affiliation must have a name and supported fields"
        ) from error


def _affiliation_payload(value: Affiliation) -> dict:
    if not isinstance(value.name, str):
        raise MetadataValidationError("affiliation name must be text")
    name = value.name.strip()
    if not name:
        raise MetadataValidationError("affiliation name is required")
    payload = {key: entry for key, entry in asdict(value).items() if entry is not None}
    payload["name"] = name
    if value.identifiers:
        payload["identifiers"] = [
            asdict(identifier) for identifier in _identifier_objects(value.identifiers)
        ]
    else:
        payload.pop("identifiers")
    if value.country_code:
        payload["country_code"] = value.country_code.strip()
    if value.raw_name:
        payload["raw_name"] = value.raw_name.strip()
    return payload


def _link_payload(value: ResourceLink) -> dict:
    if (
        not isinstance(value, ResourceLink)
        or not isinstance(value.url, str)
        or not value.url.strip()
    ):
        raise MetadataValidationError("URL must be a structured nonempty link")
    if value.kind not in {"landing_page", "full_text", "other"}:
        raise MetadataValidationError("link kind is invalid")
    result = {
        key: entry
        for key, entry in asdict(value).items()
        if entry is not None and not (key == "kind" and entry == "other")
    }
    result["url"] = value.url.strip()
    return result


def _link_payloads(values: tuple[ResourceLink, ...]) -> list[dict]:
    links: dict[str, dict] = {}
    for value in values:
        payload = _link_payload(value)
        links.setdefault(payload["url"], {}).update(payload)
    return list(links.values())


def _contributor_from_value(value: dict) -> Contributor:
    try:
        return Contributor(
            **(
                value
                | {
                    "identifiers": _identifier_objects(value.get("identifiers") or ()),
                    "affiliations": tuple(
                        _affiliation_from_value(entry) for entry in value["affiliations"]
                    )
                    if value.get("affiliations") is not None
                    else None,
                }
            )
        )
    except TypeError as error:
        raise MetadataValidationError(
            "contributor must have a display name and supported fields"
        ) from error


def metadata_from_values(values: Mapping[str, Any]) -> BibliographicMetadata:
    """Decode a neutral JSON snapshot without accepting an application/ORM object."""
    scalar_names = {field.name for field in fields(BibliographicMetadata)} - {
        "authors",
        "editors",
        "urls",
        "identifiers",
        "custom_fields",
        "keywords",
    }
    arguments = {
        name: values[name] for name in scalar_names if name in values and values[name] is not None
    }
    arguments.setdefault("title", "")
    identifiers = dict(
        _input_identifier_pairs(list((values.get("identifiers") or {}).items()), values.get("doi"))
    )
    arguments["doi"] = identifiers.get("doi")
    arguments["reference_type"] = ReferenceType(
        arguments.get("reference_type", ReferenceType.document)
    )
    return BibliographicMetadata(
        **arguments,
        authors=tuple(_contributor_from_value(value) for value in values.get("authors") or ()),
        editors=tuple(_contributor_from_value(value) for value in values.get("editors") or ()),
        urls=tuple(ResourceLink(**value) for value in values.get("urls") or ()),
        keywords=tuple(values.get("keywords") or ()),
        identifiers=tuple(Identifier(provider, value) for provider, value in identifiers.items()),
        custom_fields=tuple(
            CustomField(name, _stored_json_value(value))
            for name, value in (values.get("custom_fields") or {}).items()
        ),
    )


def record_metadata_values(record: CandidateRecord | BibliographyRecord) -> dict:
    """Project typed Provider or bibliography records into serializable metadata."""
    if isinstance(record, CandidateRecord):
        return {
            "title": record.title,
            "abstract": record.abstract,
            "authors": [asdict(value) for value in record.authors]
            if record.authors is not None
            else None,
            "keywords": list(record.keywords) if record.keywords is not None else None,
            "publication_date": record.publication_date,
            "publication_title": record.publication_title,
            "journal_abbreviation": record.journal_abbreviation,
            "volume": record.volume,
            "issue": record.issue,
            "pages": record.pages,
            "publisher": record.publisher,
            "doi": record.doi,
            "urls": [asdict(link) for link in record.urls] if record.urls is not None else None,
            "identifiers": dict(
                normalize_identifier_pairs([
                    (row.provider, row.value) for row in record.identifiers
                ])
            ),
            "reference_type": record.reference_type,
        }
    return {
        "title": record.title or None,
        "abstract": record.abstract,
        "authors": [
            {
                "display_name": value.display_name(),
                "family_name": value.family_name,
                "given_name": value.given_name,
            }
            for value in record.authors
        ],
        "editors": [
            {
                "display_name": value.display_name(),
                "family_name": value.family_name,
                "given_name": value.given_name,
            }
            for value in record.editors
        ],
        "keywords": list(record.keywords),
        "publication_date": record.publication_date,
        "publication_title": record.publication_title or record.book_title,
        "journal_abbreviation": record.journal_abbreviation,
        "volume": record.volume,
        "issue": record.issue,
        "pages": record.pages,
        "publisher": record.publisher,
        "place_published": record.location,
        "doi": record.doi,
        "reference_type": record.reference_type,
        "citation_key": record.citation_key,
        "urls": [{"url": value} for value in record.urls],
        "identifiers": dict(normalize_identifier_pairs(record.identifiers)),
        "custom_fields": dict(record.custom_fields) if record.custom_fields else None,
    }


def metadata_bibliography_record(metadata: BibliographicMetadata) -> BibliographyRecord:
    """Project rich snapshots onto the neutral bibliography formatting vocabulary."""
    from inquiro.bibliography import BibliographyRecord

    return BibliographyRecord(
        citation_key=metadata.citation_key,
        reference_type=metadata.reference_type,
        title=metadata.title,
        authors=tuple(value.bibliographic_name for value in metadata.authors),
        editors=tuple(value.bibliographic_name for value in metadata.editors),
        abstract=metadata.abstract,
        keywords=metadata.keywords,
        publication_date=metadata.publication_date,
        publication_title=metadata.publication_title,
        journal_abbreviation=metadata.journal_abbreviation,
        volume=metadata.volume,
        issue=metadata.issue,
        pages=metadata.pages,
        publisher=metadata.publisher,
        location=metadata.place_published,
        doi=dict(_identifier_pairs(metadata)).get("doi"),
        urls=tuple(value.url for value in metadata.urls),
        identifiers=tuple(pair for pair in _identifier_pairs(metadata) if pair[0] != "doi"),
        custom_fields=tuple(
            (
                value.name,
                json.dumps(value.value, ensure_ascii=False)
                if isinstance(value.value, (Mapping, tuple, list))
                else str(value.value),
            )
            for value in metadata.custom_fields
            if value.value is not None
        ),
    )
