from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from advanced_alchemy.filters import LimitOffset
from sqlalchemy import Select, func, or_, select

from quirebase.access import (
    ResourceAction,
    require_project_context,
    require_workspace_action,
    workspace_items_query,
)
from quirebase.access.scope import workspace_select
from quirebase.core.errors import ValidationFailure
from quirebase.core.persistence import select_page
from quirebase.models import (
    Attachment,
    FileRevision,
    ImportBatch,
    Item,
    ItemRead,
    ItemTag,
    LoginSession,
    ProjectItem,
    User,
)
from quirebase.projects import list_workspace_projects
from quirebase.search import search_index

from ._json_queries import (
    author_condition,
    first_contributor_sort_name,
    keyword_condition,
    uuid_array_contains,
)
from .imports import BatchConflict, ImportBatchUnavailable

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LibraryFilter:
    q: str = ""
    tag: UUID | None = None
    project: UUID | None = None
    year: str = ""
    keyword: str = ""
    author: str = ""
    has_files: bool | None = None
    reference_type: str | None = None
    keyword_exact: str | None = None
    author_last_name: str | None = None
    author_first_name: str | None = None
    publication_title: str | None = None
    import_batch: UUID | None = None


async def _library_query(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    filters: LibraryFilter,
) -> Select[tuple[Item]]:
    """Resolve visibility once for search, suggestions and metadata facets."""
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    item_query = workspace_items_query(context)
    if filters.import_batch is not None:
        batch_status = await db.scalar(
            select(ImportBatch.status)
            .where(ImportBatch.id == filters.import_batch, ImportBatch.workspace_id == workspace_id)
            .with_for_update(read=True)
        )
        if batch_status is None:
            raise ImportBatchUnavailable("import batch not found")
        if batch_status != "committed":
            raise BatchConflict("the import batch has not been committed")
        receipt = (
            select(ImportBatch.committed_item_ids)
            .where(
                ImportBatch.id == filters.import_batch,
                ImportBatch.workspace_id == workspace_id,
                ImportBatch.status == "committed",
            )
            .scalar_subquery()
        )
        item_query = item_query.where(uuid_array_contains(db, receipt, Item.id))
    matching_ids = (
        await search_index(db).matching_item_ids(db, filters.q) if filters.q.strip() else None
    )
    if matching_ids is not None:
        item_query = item_query.where(Item.id.in_(matching_ids))
    if filters.tag is not None:
        item_query = item_query.where(
            Item.id.in_(
                workspace_select(ItemTag, context)
                .with_only_columns(ItemTag.item_id)
                .where(ItemTag.tag_id == filters.tag)
            )
        )
    if filters.project:
        await require_project_context(
            db, user, workspace_id, filters.project, ResourceAction.workspace_read
        )
        item_query = item_query.where(
            Item.id.in_(
                workspace_select(ProjectItem, context)
                .with_only_columns(ProjectItem.item_id)
                .where(ProjectItem.project_id == filters.project)
            )
        )
    if filters.year:
        item_query = item_query.where(
            Item.work["date_published"].as_string().startswith(filters.year, autoescape=True)
        )
    if filters.reference_type is not None:
        item_query = item_query.where(Item.work["type"].as_string() == filters.reference_type)
    if filters.publication_title is not None:
        item_query = item_query.where(
            Item.work["container"]["title"].as_string() == filters.publication_title
        )
    if filters.keyword.strip():
        item_query = item_query.where(keyword_condition(db, filters.keyword.strip(), exact=False))
    if filters.keyword_exact is not None:
        item_query = item_query.where(keyword_condition(db, filters.keyword_exact, exact=True))
    if filters.author_first_name is not None and filters.author_last_name is None:
        raise ValidationFailure("an exact author filter requires a last name")
    if filters.author.strip() or filters.author_last_name is not None:
        item_query = item_query.where(
            author_condition(
                db,
                text=filters.author.strip(),
                last_name=filters.author_last_name,
                first_name=filters.author_first_name,
            )
        )
    if filters.has_files is not None:
        file_conditions = [
            select(model.id)
            .where(model.item_id == Item.id, model.workspace_id == workspace_id)
            .exists()
            for model in (FileRevision, Attachment)
        ]
        file_condition = or_(*file_conditions)
        item_query = item_query.where(file_condition if filters.has_files else ~file_condition)
    return item_query


async def search_library(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    q: str = "",
    tag: UUID | None = None,
    project: UUID | None = None,
    year: str = "",
    keyword: str = "",
    author: str = "",
    limit: int = 25,
    offset: int = 0,
    sort: Literal["updated", "created", "title", "published", "publication", "author"] = "updated",
    has_files: bool | None = None,
    reference_type: str | None = None,
    keyword_exact: str | None = None,
    author_last_name: str | None = None,
    author_first_name: str | None = None,
    publication_title: str | None = None,
    direction: Literal["asc", "desc"] | None = None,
    import_batch: UUID | None = None,
) -> tuple[list[Item], int]:
    item_query = await _library_query(
        db,
        user,
        workspace_id,
        LibraryFilter(
            q=q,
            tag=tag,
            project=project,
            year=year,
            keyword=keyword,
            author=author,
            has_files=has_files,
            reference_type=reference_type,
            keyword_exact=keyword_exact,
            author_last_name=author_last_name,
            author_first_name=author_first_name,
            publication_title=publication_title,
            import_batch=import_batch,
        ),
    )
    # Binary collation keeps ordering consistent across databases.
    collation = "C" if db.get_bind().dialect.name == "postgresql" else "BINARY"
    expression = {
        "updated": Item.updated_at,
        "created": Item.created_at,
        "title": Item.work["title"].as_string().collate(collation),
        "author": first_contributor_sort_name(db).collate(collation),
        "publication": func.nullif(Item.work["container"]["title"].as_string(), "").collate(
            collation
        ),
        # Publication Date is a calendar value, not an instant. Do not invent missing parts.
        "published": func.substr(Item.work["date_published"].as_string(), 1, 10).collate(collation),
    }[sort]
    direction = direction or ("asc" if sort in {"title", "publication", "author"} else "desc")
    records, total = await select_page(
        db,
        item_query.order_by(
            (expression.asc() if direction == "asc" else expression.desc()).nulls_last(), Item.id
        ),
        Item,
        LimitOffset(limit=limit, offset=offset),
    )
    return list(records), total


async def get_dashboard_data(db: AsyncSession, user: User, workspace_id: UUID) -> dict[str, Any]:
    context = await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    new_items = list(
        (
            await db.scalars(
                workspace_items_query(context).order_by(Item.created_at.desc()).limit(10)
            )
        ).all()
    )
    recent_items = list(
        (
            await db.execute(
                workspace_items_query(context)
                .join(ItemRead, ItemRead.item_id == Item.id)
                .where(
                    ItemRead.user_id == user.id,
                )
                .with_only_columns(Item, ItemRead.last_read_at)
                .order_by(ItemRead.last_read_at.desc())
                .limit(10)
            )
        ).all()
    )
    project_rows, project_count = await list_workspace_projects(db, context, view="mine", limit=10)
    projects = [project for project, _, _ in project_rows]
    sessions = list(
        (
            await db.scalars(
                select(LoginSession)
                .where(LoginSession.user_id == user.id)
                .order_by(LoginSession.created_at.desc())
                .limit(10)
            )
        ).all()
    )
    return {
        "new_items": new_items,
        "recent_items": recent_items,
        "projects": projects,
        "project_count": project_count,
        "sessions": sessions,
    }
