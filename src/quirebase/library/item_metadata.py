"""Create and revise one Item's bibliographic metadata."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import update

from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import ValidationFailure, VersionConflict
from quirebase.discovery.lookup import normalize_reference_type
from quirebase.library.authors import set_item_authors
from quirebase.library.identifiers import (
    clean_identifier_value,
    generate_bibtex_key,
    set_item_identifiers,
)
from quirebase.models import Item
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import User

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
    item_id: str
    version: int


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value else None


def _bibliographic_values(metadata: ItemMetadata) -> dict[str, object]:
    title = metadata.title.strip()
    if not title:
        raise ValidationFailure("title is required")
    return {
        "title": title,
        "abstract": _optional_text(metadata.abstract),
        "keywords": "; ".join(value.strip() for value in metadata.keywords if value.strip())
        or None,
        "publication_date": _optional_text(metadata.publication_date),
        "publication_title": _optional_text(metadata.publication_title),
        "reference_type": normalize_reference_type(metadata.reference_type or ""),
        "volume": _optional_text(metadata.volume),
        "issue": _optional_text(metadata.issue),
        "pages": _optional_text(metadata.pages),
        "affiliation": _optional_text(metadata.affiliation),
        "publisher": _optional_text(metadata.publisher),
        "place_published": _optional_text(metadata.place_published),
        "journal_abbreviation": _optional_text(metadata.journal_abbreviation),
        "bibtex_id": _optional_text(metadata.bibtex_key),
        "bibtex_type": _optional_text(metadata.bibtex_type),
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
    seen: set[tuple[str, str | None]] = set()
    for contributor in contributors:
        last_name = contributor.last_name.strip()
        first_name = _optional_text(contributor.first_name)
        if not last_name:
            raise ValidationFailure("contributor last name is required")
        if editor and contributor.is_corresponding:
            raise ValidationFailure("editors cannot be corresponding authors")
        identity = (last_name.casefold(), first_name.casefold() if first_name else None)
        if identity in seen:
            raise ValidationFailure("contributors must be unique within a role")
        seen.add(identity)
        payload.append({
            "last_name": last_name,
            "first_name": first_name,
            "is_corresponding": contributor.is_corresponding,
        })
    return payload


def _serialize_custom_fields(fields: tuple[CustomField, ...]) -> str | None:
    values: dict[str, JsonValue] = {}
    for custom_field in fields:
        name = custom_field.name.strip()
        if not name:
            raise ValidationFailure("custom field name is required")
        if name in values:
            raise ValidationFailure("custom field names must be unique")
        values[name] = custom_field.value
    return json.dumps(values, ensure_ascii=False) if values else None


def _create_item(
    db: Session,
    actor: User,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    values = _bibliographic_values(metadata)
    values.update(
        custom_fields=_serialize_custom_fields(metadata.custom_fields),
        created_by=actor.id,
    )
    item = Item(**values)
    db.add(item)
    db.flush()
    set_item_identifiers(db, actor, item.id, _identifier_pairs(metadata))
    set_item_authors(
        db,
        actor,
        item.id,
        _contributor_payload(metadata.authors, editor=False),
        role="author",
    )
    set_item_authors(
        db,
        actor,
        item.id,
        _contributor_payload(metadata.editors, editor=True),
        role="editor",
    )
    search_index(db).index_item(db, item.id)
    record_event(db, actor.id, "item.create", "item", item.id)
    db.commit()
    return ItemWriteResult(item_id=item.id, version=item.version)


def create_item(
    db: Session,
    actor: User,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    try:
        return _create_item(db, actor, metadata)
    except Exception:
        db.rollback()
        raise


def _revise_item_metadata(
    db: Session,
    actor: User,
    item_id: str,
    expected_version: int,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    require_editable_item(db, actor, item_id)
    values = _bibliographic_values(metadata)
    values.update(
        custom_fields=_serialize_custom_fields(metadata.custom_fields),
        updated_by=actor.id,
        updated_at=datetime.now(UTC),
        version=Item.version + 1,
    )
    version = db.scalar(
        update(Item)
        .where(Item.id == item_id, Item.version == expected_version)
        .values(**values)
        .returning(Item.version)
    )
    if version is None:
        db.rollback()
        current = db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)

    set_item_identifiers(db, actor, item_id, _identifier_pairs(metadata))
    set_item_authors(
        db,
        actor,
        item_id,
        _contributor_payload(metadata.authors, editor=False),
        role="author",
    )
    set_item_authors(
        db,
        actor,
        item_id,
        _contributor_payload(metadata.editors, editor=True),
        role="editor",
    )
    db.expire_all()
    search_index(db).index_item(db, item_id)
    record_event(
        db,
        actor.id,
        "item.update",
        "item",
        item_id,
        detail={"version": version},
    )
    db.commit()
    return ItemWriteResult(item_id=item_id, version=version)


def revise_item_metadata(
    db: Session,
    actor: User,
    item_id: str,
    expected_version: int,
    metadata: ItemMetadata,
) -> ItemWriteResult:
    try:
        return _revise_item_metadata(db, actor, item_id, expected_version, metadata)
    except Exception:
        db.rollback()
        raise


def _regenerate_bibtex_key(
    db: Session,
    actor: User,
    item_id: str,
    expected_version: int,
) -> ItemWriteResult:
    item = require_editable_item(db, actor, item_id)
    key = generate_bibtex_key(item)
    version = db.scalar(
        update(Item)
        .where(Item.id == item_id, Item.version == expected_version)
        .values(
            bibtex_id=key,
            updated_by=actor.id,
            updated_at=datetime.now(UTC),
            version=Item.version + 1,
        )
        .returning(Item.version)
    )
    if version is None:
        db.rollback()
        current = db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)
    db.expire_all()
    search_index(db).index_item(db, item_id)
    record_event(
        db,
        actor.id,
        "item.bibtex_key.regenerate",
        "item",
        item_id,
        detail={"version": version},
    )
    db.commit()
    return ItemWriteResult(item_id=item_id, version=version)


def regenerate_bibtex_key(
    db: Session,
    actor: User,
    item_id: str,
    expected_version: int,
) -> ItemWriteResult:
    try:
        return _regenerate_bibtex_key(db, actor, item_id, expected_version)
    except Exception:
        db.rollback()
        raise
