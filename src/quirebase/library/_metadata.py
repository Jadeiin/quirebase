"""Map neutral bibliographic snapshots onto Library-owned persistence."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

from inquiro.bibliography import generate_default_citation_key
from inquiro.metadata import (
    MetadataUpdate as MetadataWrite,
)
from inquiro.metadata import (
    MetadataValidationError,
    merge_metadata_values,
    metadata_bibliography_record,
    metadata_from_values,
    metadata_values,
)
from inquiro.metadata import (
    normalize_identifier_pairs as _normalize_identifier_pairs,
)
from inquiro.models import Affiliation, Contributor, CustomField, JsonValue, ResourceLink
from inquiro.models import BibliographicMetadata as ItemMetadata
from inquiro.models import Identifier as ExternalIdentifier
from inquiro.richtext import convert_rich_text

from quirebase.core.errors import ValidationFailure
from quirebase.models import MAX_CITATION_KEY_LENGTH

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from quirebase.models import Item, ItemIdentifier

__all__ = [
    "Affiliation",
    "Contributor",
    "CustomField",
    "ExternalIdentifier",
    "ItemMetadata",
    "ItemWriteResult",
    "JsonValue",
    "MetadataWrite",
    "ResourceLink",
    "candidate_write",
    "generate_citation_key",
    "metadata_from_item",
    "metadata_write",
    "normalize_identifier_pairs",
]

MAX_TITLE_TEXT_LENGTH = 1000
_TEXT_LIMITS = {
    "volume": 100,
    "issue": 100,
    "pages": 100,
    "place_published": 255,
    "citation_key": MAX_CITATION_KEY_LENGTH,
}


@dataclass(frozen=True)
class ItemWriteResult:
    item_id: UUID
    version: int


def normalize_identifier_pairs(pairs: Sequence[tuple[str, str]]) -> list[tuple[str, str]]:
    try:
        normalized = _normalize_identifier_pairs(pairs)
    except MetadataValidationError as error:
        raise ValidationFailure(str(error)) from error
    for provider, value in normalized:
        if len(provider) > 40:
            raise ValidationFailure("identifier provider is too long")
        if len(value) > 500:
            raise ValidationFailure("identifier value is too long")
    return normalized


def _storage_values(write: MetadataWrite) -> MetadataWrite:
    for name, limit in _TEXT_LIMITS.items():
        value = write.values.get(name)
        if isinstance(value, str) and len(value) > limit:
            raise ValidationFailure(
                f"{'Citation key' if name == 'citation_key' else name} is too long"
            )
    title = write.values.get("title")
    if (
        isinstance(title, str)
        and len(convert_rich_text(title, source="html", target="text")) > MAX_TITLE_TEXT_LENGTH
    ):
        raise ValidationFailure("title is too long")
    if write.identifiers is not None:
        normalize_identifier_pairs(write.identifiers)
    return write


def _item_snapshot(item: Item, identifiers: Mapping[str, str]) -> ItemMetadata:
    values = {
        field.name: getattr(item, field.name)
        for field in fields(ItemMetadata)
        if field.name not in {"identifiers", "doi"}
    }
    values["identifiers"] = dict(identifiers)
    try:
        return metadata_from_values(values)
    except MetadataValidationError as error:
        raise ValidationFailure(str(error)) from error


def metadata_from_item(item: Item, identifiers: Sequence[ItemIdentifier]) -> ItemMetadata:
    return _item_snapshot(item, {row.provider: row.value for row in identifiers})


def metadata_write(metadata: ItemMetadata) -> MetadataWrite:
    try:
        return _storage_values(metadata_values(metadata))
    except MetadataValidationError as error:
        raise ValidationFailure(str(error)) from error


def candidate_write(
    item: Item, record: dict, *, merge: bool, existing_identifiers: dict[str, str]
) -> MetadataWrite:
    try:
        return _storage_values(
            merge_metadata_values(_item_snapshot(item, existing_identifiers), record, merge=merge)
        )
    except MetadataValidationError as error:
        raise ValidationFailure(str(error)) from error


def generate_citation_key(item: Item) -> str:
    return generate_default_citation_key(
        metadata_bibliography_record(metadata_from_item(item, ())),
        max_length=MAX_CITATION_KEY_LENGTH,
    )
