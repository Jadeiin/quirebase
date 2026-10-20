from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import and_, case, func, literal, select, true

from quirebase.access import ResourceAction, require_workspace_action, workspace_items_query
from quirebase.core.errors import ValidationFailure
from quirebase.library._json_queries import array_elements
from quirebase.models import FileRevision, FileRevisionProcessingState, Item, User

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.selectable import CTE

    from quirebase.access import WorkspaceContext


DuplicateMode = Literal["identifier", "title", "file"]
_BATCH_SIZE = 400
_BLANK_CHARACTERS = " \t\n\r\f\v"


@dataclass(frozen=True)
class DuplicateScan:
    groups: list[list[Item]]
    scanned: int


def _identifier_keys(db: AsyncSession, context: WorkspaceContext, collation: str) -> CTE:
    scoped = workspace_items_query(context)
    resource_id = Item.work["id"].as_string().collate(collation)
    primary = scoped.with_only_columns(
        Item.id.label("item_id"),
        literal("id").collate(collation).label("source"),
        literal("").collate(collation).label("kind"),
        literal("").collate(collation).label("scheme"),
        resource_id.label("value"),
    ).where(func.trim(resource_id, _BLANK_CHARACTERS) != "")

    identifiers = array_elements(db, Item.work["identifiers"], objects=True)
    kind = identifiers.c.value["identifier_type"].as_string().collate(collation)
    scheme = case((kind == "Other", identifiers.c.value["scheme"].as_string()), else_="").collate(
        collation
    )
    value = identifiers.c.value["identifier"].as_string().collate(collation)
    secondary = (
        scoped
        .with_only_columns(
            Item.id.label("item_id"),
            literal("identifier").collate(collation).label("source"),
            kind.label("kind"),
            scheme.label("scheme"),
            value.label("value"),
        )
        .select_from(Item)
        .join(identifiers, true())
        .where(
            func.trim(kind, _BLANK_CHARACTERS) != "",
            func.trim(value, _BLANK_CHARACTERS) != "",
            (kind != "Other") | (func.trim(scheme, _BLANK_CHARACTERS) != ""),
        )
    )
    # UNION removes repeated keys within one Item before counting distinct Items.
    # Primary URIs and typed identifiers are independent, exact-value evidence.
    return primary.union(secondary).cte("duplicate_keys")


async def find_duplicates(
    db: AsyncSession, user: User, workspace_id: UUID, mode: DuplicateMode
) -> DuplicateScan:
    if mode not in ("identifier", "title", "file"):
        raise ValidationFailure(f"unknown duplicate mode: {mode}")
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    collation = "C" if db.get_bind().dialect.name == "postgresql" else "BINARY"
    scoped = workspace_items_query(context)
    if mode == "title":
        title = Item.work["title"].as_string().collate(collation)
        keys = (
            scoped
            .with_only_columns(
                Item.id.label("item_id"),
                literal("title").label("source"),
                literal("").label("kind"),
                literal("").label("scheme"),
                title.label("value"),
            )
            .where(func.trim(title, _BLANK_CHARACTERS) != "")
            .cte("duplicate_keys")
        )
    elif mode == "file":
        checksum = FileRevision.file["checksum"].as_string().collate(collation)
        keys = (
            scoped
            .with_only_columns(
                Item.id.label("item_id"),
                literal("file").label("source"),
                literal("").label("kind"),
                literal("").label("scheme"),
                checksum.label("value"),
            )
            .join(
                FileRevision,
                and_(
                    FileRevision.workspace_id == Item.workspace_id,
                    FileRevision.item_id == Item.id,
                ),
            )
            .where(
                FileRevision.processing_state == FileRevisionProcessingState.ready,
                func.trim(checksum, _BLANK_CHARACTERS) != "",
            )
            .distinct()
            .cte("duplicate_keys")
        )
    else:
        keys = _identifier_keys(db, context, collation)
    scanned = (
        await db.scalar(
            select(func.count(keys.c.item_id.distinct()))
            if mode == "file"
            else scoped.with_only_columns(func.count(Item.id))
        )
        or 0
    )
    key_columns = [keys.c.source, keys.c.kind, keys.c.scheme, keys.c.value]
    matching_keys = (
        select(*key_columns).group_by(*key_columns).having(func.count() > 1).cte("matching_keys")
    )
    # Matching and loading share a statement, avoiding stale candidate snapshots.
    rows = await db.stream(
        scoped
        .add_columns(*key_columns)
        .join(keys, Item.id == keys.c.item_id)
        .join(
            matching_keys,
            and_(*(column == matching_keys.c[column.key] for column in key_columns)),
        )
        .order_by(*key_columns, Item.id)
        .execution_options(yield_per=_BATCH_SIZE, populate_existing=True)
    )
    groups: dict[tuple[str, str, str, str], list[Item]] = {}
    try:
        async for item, source, kind, scheme, value in rows:
            groups.setdefault((source, kind, scheme, value), []).append(item)
    finally:
        await rows.close()
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    # Several shared keys can describe the same group; show its Items once.
    unique_groups = {tuple(item.id for item in group): group for group in groups.values()}
    return DuplicateScan(groups=list(unique_groups.values()), scanned=scanned)
