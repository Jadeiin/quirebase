"""Library business validation over the external Commonmeta Work contract."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from inquiro.bibliography import generate_default_citation_key
from inquiro.richtext import convert_rich_text
from inquiro.work import (
    InvalidWork,
    contributor_name,
    work_authors,
    work_doi,
    work_id_identifier,
    work_schema,
)
from pydantic import ValidationError

from quirebase.core.errors import ValidationFailure
from quirebase.models import MAX_CITATION_KEY_LENGTH

if TYPE_CHECKING:
    from uuid import UUID

    from quirebase.models import Item

from inquiro.work_models import Work


@dataclass(frozen=True)
class ItemWriteResult:
    item_id: UUID
    version: int


def metadata_write(work: Work | dict[str, Any]) -> dict[str, Any]:
    """Validate the standard Work contract and apply Library's own limits.

    A typed ``Work`` is validated again on purpose: ``model_copy(update=...)``
    and attribute assignment bypass Pydantic validation, so this write seam
    keeps the persisted payload canonical instead of trusting its callers.
    """
    try:
        if isinstance(work, Work):
            work = work.model_dump(mode="json", exclude_none=True)
        validated = Work.model_validate(work).model_dump(mode="json", exclude_none=True)
    except (InvalidWork, ValidationError) as error:
        raise ValidationFailure(str(error)) from error
    title = convert_rich_text(validated.get("title", ""), source="html", target="text").strip()
    if not title:
        raise ValidationFailure("title is required")
    if len(title) > 1000:
        raise ValidationFailure("title is too long")
    if published := validated.get("date_published"):
        try:
            if "T" in published:
                datetime.fromisoformat(published)
            else:
                parts = [int(part) for part in published.split("-")]
                date(*(parts + [1] * (3 - len(parts))))
        except ValueError as error:
            raise ValidationFailure("publication date must be a valid calendar date") from error
    if len(json.dumps(validated, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
        raise ValidationFailure("Work metadata is limited to 1 MiB")
    return {"work": validated}


def metadata_from_item(item: Item) -> Work:
    return Work.model_validate(item.work)


def validate_citation_key(key: str | None) -> str | None:
    if key is not None and (not isinstance(key, str) or len(key) > MAX_CITATION_KEY_LENGTH):
        raise ValidationFailure("Citation key is too long or invalid")
    return key


def candidate_write(work: dict[str, Any], *, current: dict[str, Any]) -> dict[str, Any]:
    """Merge one Provider or Import candidate Work into the persisted Work.

    The merge preserves omitted and additional local facts, then applies the
    same Library policy as any other write.
    """
    result = deepcopy(current)
    for key, value in work.items():
        if key == "contributors" and value:
            credits = deepcopy(result.get(key, []))
            for incoming in value:
                matches = [
                    index for index, credit in enumerate(credits) if _same_credit(credit, incoming)
                ]
                if len(matches) > 1 and (roles := set(incoming.get("roles", []))):
                    # One person can have separate Author and Editor credits.
                    # Prefer the same role set, then a credit retaining extra local roles.
                    # A unique shared-role match also permits upstream role extensions.
                    exact_roles = [
                        index for index in matches if set(credits[index].get("roles", [])) == roles
                    ]
                    matches = (
                        exact_roles
                        or [
                            index
                            for index in matches
                            if roles <= set(credits[index].get("roles", []))
                        ]
                        or [
                            index
                            for index in matches
                            if roles & set(credits[index].get("roles", []))
                        ]
                    )
                if len(matches) == 1:
                    index = matches[0]
                    credit = credits[index]
                    entity = "person" if incoming["type"] == "Person" else "organization"
                    local_entity = credit.get(entity, {})
                    incoming_entity = incoming.get(entity, {})
                    merged_entity = _merge_facts(local_entity, incoming_entity)
                    if entity == "person" and _same_joined_person_name(
                        local_entity, incoming_entity
                    ):
                        # Different readers can split a compound surname differently.
                        # Keep the local spelling while enriching this same credit.
                        for part in ("given_name", "family_name"):
                            merged_entity[part] = local_entity[part]
                    credits[index] = {
                        **credit,
                        **deepcopy(incoming),
                        entity: merged_entity,
                        "roles": list(
                            dict.fromkeys([*credit.get("roles", []), *incoming.get("roles", [])])
                        ),
                    }
                elif not any(
                    _merge_facts(credits[index], incoming) == credits[index] for index in matches
                ):
                    # Ambiguous credits must not accumulate an already represented
                    # contribution on every unchanged Provider sync.
                    credits.append(deepcopy(incoming))
            result[key] = credits
        elif isinstance(value, (list, dict)):
            result[key] = _merge_facts(result.get(key), value)
        elif key == "id" and value.startswith("urn:uuid:"):
            result.setdefault(key, value)
        else:
            result[key] = deepcopy(value)
    if (previous_id := current.get("id")) and result.get("id") != previous_id:
        result["identifiers"] = _merge_facts(
            result.get("identifiers", []), [work_id_identifier(previous_id)]
        )
    return metadata_write(result)


def _same_joined_person_name(left: dict, right: dict) -> bool:
    left_parts = (left.get("given_name"), left.get("family_name"))
    right_parts = (right.get("given_name"), right.get("family_name"))
    return all((*left_parts, *right_parts)) and (
        f"{left_parts[0]} {left_parts[1]}" == f"{right_parts[0]} {right_parts[1]}"
    )


def _same_credit(local: dict, incoming: dict) -> bool:
    if local["type"] != incoming["type"]:
        return False
    left = local.get(local["type"].lower(), {})
    right = incoming.get(incoming["type"].lower(), {})
    if left.get("id") and right.get("id"):
        return left["id"] == right["id"]
    # Complete credit names distinguish people sharing name parts, including
    # Jr/Sr. Use those supplied facts before falling back to family/given names.
    if left.get("name") and right.get("name") and left["name"] != right["name"]:
        return False
    if left.get("family_name") and right.get("family_name"):
        return (left["family_name"], left.get("given_name")) == (
            right["family_name"],
            right.get("given_name"),
        ) or _same_joined_person_name(left, right)
    return bool(left.get("name")) and left.get("name") == right.get("name")


def _merge_facts(local, incoming):
    """Keep omitted and additional local facts during a Provider merge."""
    if isinstance(local, dict) and isinstance(incoming, dict):
        result = deepcopy(local)
        for key, value in incoming.items():
            result[key] = _merge_facts(result.get(key), value)
        return result
    if isinstance(local, list) and isinstance(incoming, list):
        merged = deepcopy(local)
        for value in incoming:
            if value not in merged:
                merged.append(deepcopy(value))
        return merged
    return deepcopy(incoming)


def generate_citation_key(item: Item) -> str:
    return generate_default_citation_key(item.work, max_length=MAX_CITATION_KEY_LENGTH)


def get_work_schema() -> dict:
    return deepcopy(work_schema())


def item_summary(item: Item) -> dict:
    return {
        "id": item.id,
        "title_html": item.work.get("title", ""),
        "authors": "; ".join(contributor_name(row) for row in work_authors(item.work)) or None,
        "publication_date": item.work.get("date_published"),
        "publication_title": item.work.get("container", {}).get("title"),
        "doi": work_doi(item.work),
        "version": item.version,
    }
