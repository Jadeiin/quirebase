from __future__ import annotations

import contextlib
import json
import re
from dataclasses import asdict
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from quirebase.access.items import require_editable_item
from quirebase.discovery.bibliography import REFERENCE_TYPE_TO_BIBTEX, extract_year
from quirebase.discovery.lookup import (
    MetadataRecord,
    _clean_markup,
    lookup_metadata,
    normalize_doi,
    normalize_reference_type,
)
from quirebase.library.audit import record_audit_event
from quirebase.library.authors import parse_author_list_string, set_item_authors
from quirebase.models import FileRevision, Item, ItemIdentifier, User
from quirebase.pipeline.inspection import first_doi_from_text
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
                record_audit_event(db, user.id, "item.rescan_doi", "item", item_id)
                db.commit()
                return found_doi
    return None


def apply_metadata_record(
    db: Session,
    user: User,
    item: Item,
    record: MetadataRecord | dict,
    *,
    merge: bool = False,
) -> Item:
    """Map a metadata record onto an item.

    With merge=False (new items) list fields (urls, keywords, identifiers)
    are taken from the record; with merge=True (existing items) they are
    merged with the item's current values.
    """
    rec = asdict(record) if isinstance(record, MetadataRecord) else record

    if rec.get("title") and (title := _clean_markup(rec["title"])):
        item.title = title
    if rec.get("abstract") and (abstract := _clean_markup(rec["abstract"])):
        item.abstract = abstract
    if rec.get("publication_date") and (pub_date := str(rec["publication_date"]).strip()):
        item.publication_date = pub_date
    if rec.get("publication_title") and (pub_title := _clean_markup(rec["publication_title"])):
        item.publication_title = pub_title
    if rec.get("journal_abbreviation") and (abbr := _clean_markup(rec["journal_abbreviation"])):
        item.journal_abbreviation = abbr
    if rec.get("reference_type") and (ref_type := normalize_reference_type(rec["reference_type"])):
        item.reference_type = ref_type
        bib_type = rec.get("bibtex_type") or REFERENCE_TYPE_TO_BIBTEX.get(ref_type, ref_type)
        if bib_type:
            item.bibtex_type = str(bib_type).strip().lower()
    elif rec.get("bibtex_type"):
        item.bibtex_type = str(rec["bibtex_type"]).strip().lower()
    if rec.get("volume") and (volume := str(rec["volume"]).strip()):
        item.volume = volume
    if rec.get("issue") and (issue := str(rec["issue"]).strip()):
        item.issue = issue
    if rec.get("pages") and (pages := str(rec["pages"]).strip()):
        item.pages = pages
    if rec.get("publisher") and (publisher := _clean_markup(rec["publisher"])):
        item.publisher = publisher
    if rec.get("affiliation") and (affiliation := _clean_markup(rec["affiliation"])):
        item.affiliation = affiliation
    if rec.get("place_published") and (place := _clean_markup(rec["place_published"])):
        item.place_published = place
    if rec.get("doi") and (doi := clean_identifier_value("doi", rec["doi"])):
        item.doi = doi

    for role, raw in (("author", rec.get("authors")), ("editor", rec.get("editors"))):
        if raw:
            names = str(raw).strip()
            parsed = parse_author_list_string(names)
            if parsed:
                if role == "author":
                    item.authors = names
                else:
                    item.editors = names
                set_item_authors(db, user, item.id, parsed, role=role)

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

    if not item.bibtex_id:
        item.bibtex_id = str(rec.get("bibtex_id") or "").strip() or generate_bibtex_key(item)

    identifiers = (
        {ident.provider: ident.value for ident in get_item_identifiers(db, item.id)}
        if merge
        else {}
    )
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
    if identifiers:
        set_item_identifiers(db, user, item.id, list(identifiers.items()))

    return item


def sync_metadata_from_upstream(
    db: Session,
    user: User,
    item_id: str,
    provider: str,
    uid_value: str,
) -> Item:
    item = require_editable_item(db, user, item_id)

    _, record = lookup_metadata(uid_value, provider=provider)
    apply_metadata_record(db, user, item, record, merge=True)

    current_idents = {ident.provider: ident.value for ident in get_item_identifiers(db, item_id)}
    if provider and uid_value:
        clean_val = clean_identifier_value(provider, uid_value)
        if clean_val:
            current_idents[provider] = clean_val
    if current_idents:
        set_item_identifiers(db, user, item_id, list(current_idents.items()))
    if provider == "doi" and uid_value and not item.doi:
        item.doi = clean_identifier_value("doi", uid_value)

    item.updated_by = user.id
    item.version += 1
    db.flush()

    search_index(db).index_item(db, item_id)
    record_audit_event(db, user.id, "item.sync_upstream", "item", item_id)
    db.commit()
    return item
