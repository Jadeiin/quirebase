from __future__ import annotations

import contextlib
import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from inquiro.bibliography import REFERENCE_TYPE_TO_BIBTEX, extract_year
from inquiro.identifiers import DOI_PATTERN, normalize_doi
from inquiro.models import CandidateRecord
from inquiro.parsing import _clean_markup, normalize_reference_type
from sqlalchemy import delete, select, update

from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import VersionConflict
from quirebase.library.authors import parse_author_name, set_item_authors_from_string
from quirebase.library.providers import candidate_record_values, lookup_candidate
from quirebase.library.tag_recommendations import request_item_tag_recommendation
from quirebase.models import FileRevision, Item, ItemIdentifier, User
from quirebase.pipeline.inspection import first_doi_from_text
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.core.config import Settings


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


def clean_identifier_value(provider: str, value: str) -> str:
    cleaned = value.strip()
    if provider.lower() == "doi":
        cleaned = normalize_doi(cleaned).rstrip(".,; ")
    return cleaned


def set_item_identifiers(
    db: Session,
    user: User,
    item_id: str,
    id_pairs: list[tuple[str, str]],
) -> list[ItemIdentifier]:
    item = require_editable_item(db, user, item_id)

    db.execute(delete(ItemIdentifier).where(ItemIdentifier.item_id == item_id))
    db.flush()

    links: list[ItemIdentifier] = []
    idents_dict: dict[str, str] = {}
    doi_value: str | None = None

    for provider, val in id_pairs:
        prov = provider.strip().lower()
        cleaned_val = clean_identifier_value(prov, val)
        if not prov or not cleaned_val:
            continue
        if prov == "doi":
            # DOI is canonical on Item; it is not an upstream identifier row.
            doi_value = cleaned_val
            continue
        link = ItemIdentifier(item_id=item_id, provider=prov, value=cleaned_val)
        db.add(link)
        links.append(link)
        idents_dict[prov] = cleaned_val

    item.doi = doi_value
    item.identifiers = json.dumps(idents_dict) if idents_dict else None
    db.flush()
    return links


def get_item_identifiers(db: Session, item_id: str) -> list[ItemIdentifier]:
    return list(db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)).all())


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


def rescan_pdf_doi(db: Session, user: User, item_id: str) -> str | None:
    item = require_editable_item(db, user, item_id)

    revisions = list(
        db.scalars(
            select(FileRevision)
            .where(FileRevision.item_id == item_id)
            .order_by(FileRevision.created_at.desc())
        ).all()
    )
    for rev in revisions:
        if rev.full_text:
            found_doi = first_doi_from_text(rev.full_text)
            if found_doi:
                # Update item identifiers
                existing_pairs = [
                    (ident.provider, ident.value)
                    for ident in get_item_identifiers(db, item_id)
                    if ident.provider != "doi"
                ]
                existing_pairs.append(("doi", found_doi))
                set_item_identifiers(db, user, item_id, existing_pairs)
                item.updated_by = user.id
                item.updated_at = datetime.now(UTC)
                item.version += 1
                db.flush()
                search_index(db).index_item(db, item_id)
                record_event(db, user.id, "item.rescan_doi", "item", item_id)
                db.commit()
                return found_doi
    return None


def apply_metadata_record(
    db: Session,
    user: User,
    item: Item,
    record: CandidateRecord | dict,
    *,
    merge: bool = False,
    forced_identifiers: dict[str, str] | None = None,
) -> Item:
    """Map a metadata record onto an item.

    With merge=False (new items) list fields (urls, keywords, identifiers)
    are taken from the record; with merge=True (existing items) they are
    merged with the item's current values.
    """
    rec = candidate_record_values(record) if isinstance(record, CandidateRecord) else record

    scalar_fields = {
        "title": ("title", _clean_markup),
        "abstract": ("abstract", _clean_markup),
        "publication_date": ("publication_date", lambda value: str(value).strip()),
        "publication_title": ("publication_title", _clean_markup),
        "journal_abbreviation": ("journal_abbreviation", _clean_markup),
        "volume": ("volume", lambda value: str(value).strip()),
        "issue": ("issue", lambda value: str(value).strip()),
        "pages": ("pages", lambda value: str(value).strip()),
        "publisher": ("publisher", _clean_markup),
        "affiliation": ("affiliation", _clean_markup),
        "place_published": ("place_published", _clean_markup),
    }
    for field, (record_field, transform) in scalar_fields.items():
        value = rec.get(record_field)
        if value and (cleaned_value := transform(value)):
            setattr(item, field, cleaned_value)

    if rec.get("reference_type") and (ref_type := normalize_reference_type(rec["reference_type"])):
        item.reference_type = ref_type
        bib_type = rec.get("bibtex_type") or REFERENCE_TYPE_TO_BIBTEX.get(ref_type, ref_type)
        if bib_type:
            item.bibtex_type = str(bib_type).strip().lower()
    elif rec.get("bibtex_type"):
        item.bibtex_type = str(rec["bibtex_type"]).strip().lower()

    for role, raw in (("author", rec.get("authors")), ("editor", rec.get("editors"))):
        if raw:
            if role == "author":
                item.authors = str(raw).strip() or None
            else:
                item.editors = str(raw).strip() or None
            set_item_authors_from_string(db, user, item, role=role)

    if merge:
        urls = [u.strip() for u in (item.urls or "").splitlines() if u.strip()]
        keywords = [k.strip() for k in (item.keywords or "").split(";") if k.strip()]
    else:
        urls = []
        keywords = []
    for url in str(rec.get("urls") or "").splitlines():
        url = url.strip()
        if url and url not in urls:
            urls.append(url)
    for keyword in str(rec.get("keywords") or "").split(";"):
        keyword = keyword.strip()
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    if rec.get("urls") or not merge:
        item.urls = "\n".join(urls) if urls else None
    if rec.get("keywords") or not merge:
        item.keywords = "; ".join(keywords) if keywords else None

    raw_custom_fields = rec.get("custom_fields")
    if raw_custom_fields:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed_custom_fields = (
                json.loads(raw_custom_fields)
                if isinstance(raw_custom_fields, str)
                else raw_custom_fields
            )
            if isinstance(parsed_custom_fields, dict):
                item.custom_fields = json.dumps(parsed_custom_fields, ensure_ascii=False)

    if not item.bibtex_id:
        item.bibtex_id = str(rec.get("bibtex_id") or "").strip() or generate_bibtex_key(item)

    identifiers = (
        {ident.provider: ident.value for ident in get_item_identifiers(db, item.id)}
        if merge
        else {}
    )
    if merge and item.doi:
        # DOI is canonical on Item rather than an ItemIdentifier row. Seed it
        # into the merge so non-DOI providers cannot erase it by omission.
        identifiers["doi"] = item.doi
    raw_idents = rec.get("identifiers")
    if raw_idents:
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            parsed = json.loads(raw_idents) if isinstance(raw_idents, str) else raw_idents
            if isinstance(parsed, dict):
                for provider, value in parsed.items():
                    if isinstance(value, str) and value.strip():
                        identifiers[provider] = clean_identifier_value(provider, value)
    if rec.get("doi") and (doi := clean_identifier_value("doi", rec["doi"])):
        identifiers["doi"] = doi
    for provider, value in (forced_identifiers or {}).items():
        cleaned_value = clean_identifier_value(provider, value)
        if cleaned_value:
            identifiers[provider] = cleaned_value
    if identifiers:
        set_item_identifiers(db, user, item.id, list(identifiers.items()))

    return item


def create_item_from_metadata_record(
    db: Session,
    user: User,
    record: CandidateRecord | dict,
) -> Item:
    """Create an imported Item and enqueue its initial Tag recommendation."""
    item = Item(title="Untitled", created_by=user.id)
    db.add(item)
    db.flush()
    apply_metadata_record(db, user, item, record)
    request_item_tag_recommendation(db, item.id, owner_id=user.id)
    return item


def _sync_metadata_from_upstream(
    db: Session,
    user: User,
    item_id: str,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    item = require_editable_item(db, user, item_id)
    previous_generated_key = generate_bibtex_key(item)
    previous_key = item.bibtex_id

    from quirebase.operations.settings import get_effective_settings_model

    effective_settings = settings or get_effective_settings_model(db)
    record = lookup_candidate(uid_value, provider, effective_settings)
    upstream_identifier = record.identifier
    version = db.scalar(
        update(Item)
        .where(Item.id == item_id, Item.version == expected_version)
        .values(
            updated_by=user.id,
            updated_at=datetime.now(UTC),
            version=Item.version + 1,
        )
        .returning(Item.version)
    )
    if version is None:
        db.rollback()
        current = db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)

    db.refresh(item)
    normalized_upstream_value = normalize_doi(upstream_identifier.value)
    forced_identifiers = (
        {upstream_identifier.provider: upstream_identifier.value}
        if upstream_identifier.provider
        and upstream_identifier.value
        and not DOI_PATTERN.fullmatch(normalized_upstream_value)
        else None
    )
    apply_metadata_record(
        db,
        user,
        item,
        record,
        merge=True,
        forced_identifiers=forced_identifiers,
    )

    # Upstream changes commonly alter the title, first author or year. Keep a
    # key that was generated from the previous metadata in sync, while leaving
    # an explicitly edited key untouched.
    if not previous_key or previous_key == previous_generated_key:
        regenerated_key = generate_bibtex_key(item)
        if regenerated_key != item.bibtex_id:
            item.bibtex_id = regenerated_key

    db.flush()

    search_index(db).index_item(db, item_id)
    request_item_tag_recommendation(db, item_id, owner_id=user.id)
    record_event(
        db,
        user.id,
        "item.sync_upstream",
        "item",
        item_id,
        detail={
            "provider": upstream_identifier.provider,
            "old_bibtex_key": previous_key,
            "new_bibtex_key": item.bibtex_id,
            "bibtex_key_updated": bool(
                previous_key != item.bibtex_id
                and (not previous_key or previous_key == previous_generated_key)
            ),
        },
    )
    db.commit()
    return item


def sync_metadata_from_upstream(
    db: Session,
    user: User,
    item_id: str,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    try:
        return _sync_metadata_from_upstream(
            db,
            user,
            item_id,
            expected_version,
            provider,
            uid_value,
            settings,
        )
    except Exception:
        db.rollback()
        raise
