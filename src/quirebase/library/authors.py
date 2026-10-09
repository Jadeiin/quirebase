from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.bibliography import Contributor as BibliographyContributor
from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_editable_item
from quirebase.core.errors import ValidationFailure
from quirebase.models import Author, Item, ItemAuthor, User, normalize_author_identity

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


def parse_author_name(name_str: str) -> tuple[str, str | None]:
    cleaned = " ".join(name_str.split())
    if not cleaned:
        raise ValidationFailure("author name cannot be empty")
    if "," in cleaned:
        parts = cleaned.split(",", 1)
        last = parts[0].strip()
        first = parts[1].strip() or None
        return last, first
    parts = cleaned.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[-1], " ".join(parts[:-1])


def parse_author_list_string(raw: str | None) -> list[dict[str, str | None]]:
    """Parse cached names while preserving single-field/literal contributors."""

    if not raw or not raw.strip():
        return []
    authors: list[dict[str, str | None]] = []
    for part in raw.split(";"):
        cleaned = part.strip()
        if not cleaned:
            continue
        contributor = BibliographyContributor.parse(cleaned)
        authors.append({
            "last_name": contributor.family_name,
            "first_name": contributor.given_name,
        })
    return authors


async def _resolve_authors(
    db: AsyncSession, names: Sequence[tuple[str, str | None]]
) -> dict[str, Author]:
    """Resolve shared identities in batches without committing the caller's transaction."""
    candidates: dict[str, tuple[str, str | None]] = {}
    for last_name, first_name in names:
        last = " ".join(last_name.split())
        first = " ".join(first_name.split()) or None if first_name else None
        if not last:
            raise ValidationFailure("author last name is required")
        if len(last) > 120 or (first is not None and len(first) > 120):
            raise ValidationFailure("author name is too long")
        candidates.setdefault(normalize_author_identity(last, first), (last, first))
    if not candidates:
        return {}

    resolved = await _existing_author_identities(db, set(candidates))
    pending = set(candidates) - resolved.keys()
    while pending:
        try:
            async with db.begin_nested():
                created: list[Author] = []
                ordered = sorted(pending)
                for offset in range(0, len(ordered), 500):
                    batch = [
                        Author(
                            identity_key=key,
                            last_name=candidates[key][0],
                            first_name=candidates[key][1],
                        )
                        for key in ordered[offset : offset + 500]
                    ]
                    db.add_all(batch)
                    await db.flush()
                    created.extend(batch)
        except IntegrityError:
            installed = await _existing_author_identities(db, pending)
            if not installed:
                raise
            resolved.update(installed)
            pending -= installed.keys()
        else:
            resolved.update({author.identity_key: author for author in created})
            break
    return resolved


async def find_or_create_author(
    db: AsyncSession, last_name: str, first_name: str | None = None
) -> Author:
    resolved = await _resolve_authors(db, [(last_name, first_name)])
    return resolved[normalize_author_identity(last_name, first_name)]


def _prepared_contributors(authors_data: list[dict]) -> list[tuple[int, str, str | None, bool]]:
    identities: set[str] = set()
    prepared: list[tuple[int, str, str | None, bool]] = []
    for position, entry in enumerate(authors_data, start=1):
        last = str(entry.get("last_name", "")).strip()
        raw_first = entry.get("first_name")
        first = str(raw_first).strip() or None if raw_first else None
        if not last:
            continue
        if len(last) > 120 or (first is not None and len(first) > 120):
            raise ValidationFailure("author name is too long")
        identity = normalize_author_identity(last, first)
        if identity in identities:
            raise ValidationFailure("contributors must be unique within a role")
        identities.add(identity)
        prepared.append((position, last, first, bool(entry.get("is_corresponding", False))))
    return prepared


async def _replace_item_authors_many(
    db: AsyncSession,
    replacements: Sequence[tuple[Item, str, list[dict]]],
    *,
    replace: bool = True,
) -> list[ItemAuthor]:
    """Maintain links and display caches for roots already authorized by the owning command."""
    prepared = [(item, role, _prepared_contributors(data)) for item, role, data in replacements]
    names = [(last, first) for _, _, entries in prepared for _, last, first, _ in entries]
    resolved = await _resolve_authors(db, names)
    if replace:
        roots = [(item.id, role) for item, role, _ in prepared]
        for offset in range(0, len(roots), 500):
            await db.execute(
                delete(ItemAuthor).where(
                    tuple_(ItemAuthor.item_id, ItemAuthor.role).in_(roots[offset : offset + 500])
                )
            )
    links: list[ItemAuthor] = []
    for item, role, entries in prepared:
        formatted_names: list[str] = []
        for position, last, first, corresponding in entries:
            author = resolved[normalize_author_identity(last, first)]
            links.append(
                ItemAuthor(
                    item_id=item.id,
                    author_id=author.id,
                    position=position,
                    role=role,
                    is_corresponding=corresponding,
                )
            )
            formatted_names.append(BibliographyContributor(last, first).display_name())
        cached = "; ".join(formatted_names) or None
        if role == "author":
            item.authors = cached
        elif role == "editor":
            item.editors = cached
    db.add_all(links)
    await db.flush()
    return links


async def set_item_authors(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    authors_data: list[dict],
    role: str = "author",
) -> list[ItemAuthor]:
    item = await require_editable_item(db, user, workspace_id, item_id)
    return await _replace_item_authors_many(db, [(item, role, authors_data)])


async def set_item_authors_from_string(
    db: AsyncSession,
    user: User,
    item: Item,
    role: str = "author",
) -> list[ItemAuthor]:
    raw = item.authors if role == "author" else item.editors
    parsed_authors = parse_author_list_string(raw)
    if not parsed_authors:
        return []
    return await set_item_authors(db, user, item.workspace_id, item.id, parsed_authors, role=role)


async def get_item_authors(
    db: AsyncSession, item_id: UUID, role: str = "author"
) -> list[ItemAuthor]:
    return list(
        (
            await db.scalars(
                select(ItemAuthor)
                .options(selectinload(ItemAuthor.author))
                .where(ItemAuthor.item_id == item_id, ItemAuthor.role == role)
                .order_by(ItemAuthor.position)
            )
        ).all()
    )


async def search_authors_typeahead(
    db: AsyncSession, user: User, workspace_id: UUID, query: str, limit: int = 10
) -> list[dict]:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    term = query.strip()
    if not term:
        return []
    pattern = f"{term}%"
    linked_item = (
        select(ItemAuthor.id)
        .join(Item, Item.id == ItemAuthor.item_id)
        .where(ItemAuthor.author_id == Author.id, Item.workspace_id == workspace_id)
        .exists()
    )
    stmt = (
        select(Author)
        .where(
            linked_item,
            or_(
                Author.last_name.ilike(pattern),
                Author.first_name.ilike(pattern),
            ),
        )
        .order_by(Author.last_name, Author.first_name)
        .limit(limit)
    )
    authors = list((await db.scalars(stmt)).all())
    return [
        {
            "id": a.id,
            "last_name": a.last_name,
            "first_name": a.first_name,
            "full_name": f"{a.last_name}, {a.first_name}" if a.first_name else a.last_name,
        }
        for a in authors
    ]


async def _existing_author_identities(db: AsyncSession, keys: set[str]) -> dict[str, Author]:
    found: dict[str, Author] = {}
    ordered = sorted(keys)
    for offset in range(0, len(ordered), 500):
        found.update({
            author.identity_key: author
            for author in await db.scalars(
                select(Author).where(Author.identity_key.in_(ordered[offset : offset + 500]))
            )
        })
    return found
