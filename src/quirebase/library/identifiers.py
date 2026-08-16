from __future__ import annotations

import contextlib
import json
import re
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from quirebase.access.items import require_editable_item
from quirebase.core.errors import ValidationFailure
from quirebase.discovery.lookup import DOI_PATTERN, lookup_metadata
from quirebase.library.audit import record_audit_event
from quirebase.library.authors import parse_author_name, set_item_authors
from quirebase.models import FileRevision, Item, ItemIdentifier, User
from quirebase.search import search_index

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

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
        cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^doi:\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.rstrip(".,; ")
    return cleaned


def set_item_identifiers(
    db: Session,
    user: User,
    item_id: str,
    id_pairs: list[tuple[str, str]],
) -> list[ItemIdentifier]:
    require_editable_item(db, user, item_id)
    item = db.get(Item, item_id)
    if item is None:
        raise ValidationFailure("item not found")

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
        link = ItemIdentifier(item_id=item_id, provider=prov, value=cleaned_val)
        db.add(link)
        links.append(link)
        idents_dict[prov] = cleaned_val
        if prov == "doi":
            doi_value = cleaned_val

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
        last_name = first_author.split(",")[0].strip()
        # Clean non-alphanumeric
        last_clean = re.sub(r"[^A-Za-z0-9]", "", last_name)
        if last_clean:
            author_part = last_clean.capitalize()

    year_part = "XXXX"
    if item.publication_date:
        match = re.search(r"\b(19\d\d|20\d\d)\b", item.publication_date)
        if match:
            year_part = match.group(1)

    title_part = "Work"
    if item.title:
        words = re.findall(r"[A-Za-z0-9]+", item.title)
        for word in words:
            if word.lower() not in STOP_WORDS and len(word) > 2:
                title_part = word.capitalize()
                break

    return f"{author_part}{year_part}{title_part}"


def rescan_pdf_doi(db: Session, user: User, item_id: str) -> str | None:
    require_editable_item(db, user, item_id)
    item = db.get(Item, item_id)
    if item is None:
        raise ValidationFailure("item not found")

    revisions = list(
        db.scalars(
            select(FileRevision)
            .where(FileRevision.item_id == item_id)
            .order_by(FileRevision.created_at.desc())
        ).all()
    )
    for rev in revisions:
        if rev.full_text:
            match = DOI_PATTERN.search(rev.full_text)
            if match:
                found_doi = match.group(0).rstrip(".,; )]")
                # Update item identifiers
                existing_pairs = [
                    (ident.provider, ident.value)
                    for ident in get_item_identifiers(db, item_id)
                    if ident.provider != "doi"
                ]
                existing_pairs.append(("doi", found_doi))
                set_item_identifiers(db, user, item_id, existing_pairs)
                item.updated_by = user.id
                record_audit_event(db, user.id, "item.rescan_doi", "item", item_id)
                db.flush()
                return found_doi
    return None


def sync_metadata_from_upstream(
    db: Session,
    user: User,
    item_id: str,
    provider: str,
    uid_value: str,
) -> Item:
    require_editable_item(db, user, item_id)
    item = db.get(Item, item_id)
    if item is None:
        raise ValidationFailure("item not found")

    _, record = lookup_metadata(uid_value, provider=provider)

    if record.get("title"):
        item.title = record["title"] or item.title
    if record.get("abstract"):
        item.abstract = record["abstract"]
    if record.get("publication_date"):
        item.publication_date = record["publication_date"]
    if record.get("publication_title"):
        item.publication_title = record["publication_title"]
    if record.get("reference_type"):
        item.reference_type = record["reference_type"]
    if record.get("volume"):
        item.volume = record["volume"]
    if record.get("issue"):
        item.issue = record["issue"]
    if record.get("pages"):
        item.pages = record["pages"]
    if record.get("publisher"):
        item.publisher = record["publisher"]
    if record.get("affiliation"):
        item.affiliation = record["affiliation"]
    if record.get("journal_abbreviation"):
        item.journal_abbreviation = record["journal_abbreviation"]
    if record.get("doi"):
        item.doi = record["doi"]
    elif provider == "doi":
        item.doi = uid_value

    authors_raw = record.get("authors")
    if isinstance(authors_raw, str) and authors_raw.strip():
        parsed_authors = []
        for author_str in authors_raw.split(";"):
            author_str = author_str.strip()
            if author_str:
                last, first = parse_author_name(author_str)
                parsed_authors.append({"last_name": last, "first_name": first})
        if parsed_authors:
            set_item_authors(db, user, item_id, parsed_authors, role="author")

    idents_raw = record.get("identifiers")
    current_idents = {ident.provider: ident.value for ident in get_item_identifiers(db, item_id)}
    if provider and uid_value:
        clean_val = clean_identifier_value(provider, uid_value)
        if clean_val:
            current_idents[provider] = clean_val
    if isinstance(idents_raw, str) and idents_raw.strip():
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            idents = json.loads(idents_raw)
            if isinstance(idents, dict):
                for p, v in idents.items():
                    if isinstance(v, str) and v.strip():
                        current_idents[p] = clean_identifier_value(p, v)
    if current_idents:
        set_item_identifiers(db, user, item_id, list(current_idents.items()))

    item.updated_by = user.id
    item.version += 1
    db.flush()

    search_index(db).index_item(db, item_id)
    record_audit_event(db, user.id, "item.sync_upstream", "item", item_id)
    db.flush()
    return item
