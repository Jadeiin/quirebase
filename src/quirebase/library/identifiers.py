from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import groupby
from typing import TYPE_CHECKING
from unicodedata import normalize
from urllib.parse import parse_qs, unquote, urlsplit
from xml.etree import ElementTree

from inquiro import Identifier
from inquiro.identifiers import ARXIV_PATTERN, DOI_PATTERN, canonical_doi, parse_arxiv
from inquiro.work import normalize_identifier, work_doi, work_identifiers
from sqlalchemy import update

from quirebase.access import ResourceAction, WorkspaceContext, get_item, require_action
from quirebase.access.items import require_editable_item
from quirebase.audit import record_event
from quirebase.core.errors import ResourceUnavailable, VersionConflict
from quirebase.documents.pdf import read_pdf_metadata
from quirebase.library.providers import get_metadata_provider_choices, lookup_candidate
from quirebase.library.workflows import request_item_tag_recommendation
from quirebase.models import Item, User
from quirebase.search import search_index

from ._metadata import candidate_write, generate_citation_key, metadata_write, validate_citation_key

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.core.config import Settings
    from quirebase.documents.pdf import PdfTextLine


_PDF_ARXIV_WATERMARK = re.compile(
    rf"^arxiv:\s*({ARXIV_PATTERN.pattern})(?=\s|$)",
    re.IGNORECASE,
)
_XMP_DOI_FIELDS = {
    f"{{http://prismstandard.org/namespaces/basic/{version}/}}doi"
    for version in ("1.0", "2.0", "3.0")
} | {
    "{http://ns.adobe.com/pdfx/1.3/}doi",
    "{http://ns.adobe.com/pdfx/1.3/}DOI",
    "{http://purl.org/dc/elements/1.1/}identifier",
}
_PDF_DOI_LABEL = re.compile(
    r"^\s*(?:digital\s+object\s+identifier\s*:?|doi\s*:)\s*(10\.\d{4,9}/\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_PDF_SELF_CITATION = re.compile(
    r"^\s*cite\s+this(?:\s+(?:article|paper))?\s*:", re.IGNORECASE | re.MULTILINE
)
_PDF_REFERENCES = re.compile(
    r"^\s*(?:(?:\d+|[ivxlcdm]+)[.)]?\s+)?(?:references|bibliography|literature cited)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _metadata_doi(value: str) -> str | None:
    """Accept an entire identifier value, never a DOI substring from prose or a list."""
    normalized = canonical_doi(re.sub(r"^urn:doi:", "", value.strip(), flags=re.IGNORECASE))
    if DOI_PATTERN.fullmatch(normalized) and len(re.findall(r"10\.\d{4,9}/", normalized)) == 1:
        return normalized
    return None


def _xmp_dois(xml: str) -> set[str]:
    if not xml:
        return set()
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        return set()
    values: list[str] = []
    for node in root.iter():
        if node.tag in _XMP_DOI_FIELDS:
            values.extend(node.itertext())
        values.extend(value for key, value in node.attrib.items() if key in _XMP_DOI_FIELDS)
    return {doi for value in values if (doi := _metadata_doi(value))}


def _publisher_link_dois(uri: str) -> set[str]:
    try:
        url = urlsplit(uri)
    except ValueError:
        return set()
    if url.scheme not in {"http", "https"} or not url.hostname:
        return set()
    query = parse_qs(url.query)
    path = url.path.rstrip("/")
    values = []
    if (
        url.hostname == "crossmark.crossref.org" and path == "/dialog"
    ) or path == "/action/showCitFormats":
        values = query.get("doi", [])
    elif (
        url.hostname in {"mdpi.com", "www.mdpi.com"}
        and path.startswith("/article/")
        and query.get("type") == ["check_update"]
    ):
        values = [unquote(path.removeprefix("/article/"))]
    return {doi for value in values if (doi := _metadata_doi(value))}


def _printed_identity_dois(lines: Sequence[PdfTextLine]) -> set[str]:
    """Read explicit first-page identity labels, keeping self-citations in their text block."""
    candidates: set[str] = set()
    for _block_index, block in groupby(lines, key=lambda line: line.block_index):
        text = "\n".join(
            normalize("NFKC", line.text)
            for line in block
            if line.direction[0] > 0.9 and abs(line.direction[1]) < 0.1
        )
        if _PDF_REFERENCES.search(text):
            break
        values = [match[1] for match in _PDF_DOI_LABEL.finditer(text)]
        if citation := _PDF_SELF_CITATION.search(text):
            values.extend(DOI_PATTERN.findall(text[citation.end() :]))
        candidates.update(doi for value in values if (doi := _metadata_doi(value.rstrip(".,;"))))
    return candidates


def extract_pdf_lookup_identifier(path: Path) -> Identifier | None:
    """Choose one document-level identifier, rejecting body citations and ambiguous evidence."""
    metadata = read_pdf_metadata(path)
    arxiv_ids = set()
    for line in metadata.first_page_lines:
        if not (
            0 <= line.bounds[0] < line.bounds[2] <= min(72, metadata.first_page_width * 0.1)
            and abs(line.direction[0]) < 0.1
            and line.direction[1] < -0.9
        ):
            continue
        if match := _PDF_ARXIV_WATERMARK.match(line.text.strip()):
            arxiv_ids.add(match[1])
    if arxiv_ids:
        return parse_arxiv(next(iter(arxiv_ids)), "arxiv") if len(arxiv_ids) == 1 else None

    # XMP is document-level evidence. Publisher update/citation links are weaker; ordinary
    # doi.org and /lookup/doi links can point at references, so they are deliberately excluded.
    candidates = _xmp_dois(metadata.xmp)
    if not candidates:
        candidates = {doi for uri in metadata.first_page_links for doi in _publisher_link_dois(uri)}
    if not candidates:
        candidates = {
            doi
            for field in ("title", "subject")
            if (doi := _metadata_doi(metadata.info.get(field, "")))
        }
    if not candidates:
        candidates = _printed_identity_dois(metadata.first_page_lines)
    if len(candidates) == 1:
        return Identifier("doi", next(iter(candidates)))
    return None


@dataclass(frozen=True)
class MetadataSourceProvider:
    id: str
    name: str


@dataclass(frozen=True)
class ItemMetadataSource:
    namespace: str
    value: str
    providers: tuple[MetadataSourceProvider, ...]


@dataclass(frozen=True)
class ItemMetadataSources:
    version: int
    sources: tuple[ItemMetadataSource, ...]


async def get_item_metadata_sources(
    db: AsyncSession,
    context: WorkspaceContext,
    item_id: UUID,
    *,
    settings: Settings,
) -> ItemMetadataSources:
    """Resolve sync targets from one authorized Work snapshot without Provider I/O."""
    require_action(context, ResourceAction.workspace_read)
    item = await get_item(db, context, item_id)
    if item is None:
        raise ResourceUnavailable("Item not found")
    identifiers = dict.fromkeys(sorted(work_identifiers({"id": item.work.get("id", "")})), True)
    for row in item.work.get("identifiers", []):
        namespace = (
            row.get("scheme", "") if row["identifier_type"] == "Other" else row["identifier_type"]
        )
        normalized = normalize_identifier(namespace, row["identifier"])
        pair = normalized or (namespace.lower(), row["identifier"])
        identifiers[pair] = normalized is not None
    primary_doi = work_doi(item.work)
    choices = get_metadata_provider_choices(settings).lookup
    sources = tuple(
        ItemMetadataSource(
            namespace=namespace,
            value=value,
            providers=tuple(
                MetadataSourceProvider(choice.id, choice.name)
                for choice in choices
                if identifiers[namespace, value] and namespace in choice.identifier_namespaces
            ),
        )
        for namespace, value in sorted(identifiers, key=lambda pair: pair != ("doi", primary_doi))
    )
    return ItemMetadataSources(version=item.version, sources=sources)


async def _merge_metadata_work(
    db: AsyncSession,
    user: User,
    item: Item,
    work: dict,
) -> Item:
    item = await require_editable_item(db, user, item.workspace_id, item.id)
    write = candidate_write(work, current=item.work)
    item.work = write["work"]
    if not item.citation_key:
        item.citation_key = generate_citation_key(item)
    await db.flush()
    return item


async def _sync_metadata_from_upstream(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    user_id = user.id
    item = await require_editable_item(db, user, workspace_id, item_id)
    previous_generated_key = generate_citation_key(item)
    previous_key = item.citation_key

    from quirebase.operations.settings import get_effective_settings_model

    effective_settings = settings or await get_effective_settings_model(db)
    # Do not keep the read transaction open while waiting on the provider.
    # Re-read the item and enforce its expected version after the external call.
    await db.rollback()
    record = await lookup_candidate(uid_value, provider, effective_settings)
    reloaded_user = await db.get(User, user_id)
    if reloaded_user is None or not reloaded_user.active:
        raise ResourceUnavailable("user not available")
    user = reloaded_user
    item = await require_editable_item(db, user, workspace_id, item_id)
    version = await db.scalar(
        update(Item)
        .where(
            Item.workspace_id == workspace_id, Item.id == item_id, Item.version == expected_version
        )
        .values(updated_by=user.id, updated_at=datetime.now(UTC), version=Item.version + 1)
        .returning(Item.version)
    )
    if version is None:
        await db.rollback()
        current = await db.get(Item, item_id)
        raise VersionConflict(current.version if current else None)

    await db.refresh(item)
    await _merge_metadata_work(
        db,
        user,
        item,
        record.work,
    )

    # Upstream changes commonly alter the title, first author or year. Keep a
    # key that was generated from the previous metadata in sync, while leaving
    # an explicitly edited key untouched.
    if not previous_key or previous_key == previous_generated_key:
        regenerated_key = generate_citation_key(item)
        if regenerated_key != item.citation_key:
            item.citation_key = regenerated_key

    await db.flush()

    await search_index(db).index_item(db, item_id)
    await request_item_tag_recommendation(
        db,
        item_id,
        workspace_id=item.workspace_id,
        actor_id=user.id,
        force=True,
    )
    record_event(
        db,
        user.id,
        "item.sync_upstream",
        "item",
        item_id,
        detail={
            "provider": record.provider,
            "lookup_provider": provider,
            "old_citation_key": previous_key,
            "new_citation_key": item.citation_key,
            "citation_key_updated": bool(
                previous_key != item.citation_key
                and (not previous_key or previous_key == previous_generated_key)
            ),
        },
        workspace_id=item.workspace_id,
        authorization_resource_action=ResourceAction.item_update.value,
    )
    await db.commit()
    return item


async def sync_metadata_from_upstream(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    expected_version: int,
    provider: str,
    uid_value: str,
    settings: Settings | None = None,
) -> Item:
    try:
        return await _sync_metadata_from_upstream(
            db,
            user,
            workspace_id,
            item_id,
            expected_version,
            provider,
            uid_value,
            settings,
        )
    except Exception:
        await db.rollback()
        raise


async def _create_items_from_candidates(
    db: AsyncSession, workspace_id: UUID, actor_id: UUID, records: Sequence[dict]
) -> list[Item]:
    items = [
        Item(
            work=metadata_write(record["work"])["work"],
            citation_key=validate_citation_key(record.get("citation_key")),
            workspace_id=workspace_id,
            created_by=actor_id,
        )
        for record in records
    ]
    db.add_all(items)
    await db.flush()
    for item in items:
        if not item.citation_key:
            item.citation_key = generate_citation_key(item)
    await db.flush()
    return items
