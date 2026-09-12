from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Select, exists, or_, select
from sqlalchemy.orm import selectinload

from quirebase.core.errors import ResourceNotFound, ResourceUnavailable, ValidationFailure
from quirebase.models import (
    Item,
    ItemAuthor,
    ItemLifecycleState,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    ProjectState,
    SystemRole,
    User,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


def visible_items_query(user: User) -> Select[tuple[Item]]:
    query = select(Item).where(Item.lifecycle_state == ItemLifecycleState.active)
    if user.role == SystemRole.administrator.value:
        return query
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
    return query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))


async def can_read_item(db: AsyncSession, user: User, item_id: str) -> bool:
    if user.role == SystemRole.administrator.value:
        return bool(
            await db.scalar(
                select(Item.id).where(
                    Item.id == item_id, Item.lifecycle_state == ItemLifecycleState.active
                )
            )
        )
    own = exists().where(
        Item.id == item_id,
        Item.created_by == user.id,
        Item.lifecycle_state == ItemLifecycleState.active,
    )
    # The shared branch must restate the Item conditions: without them the
    # ProjectItem link alone would keep a persistently deleting Item readable
    # to project members during durable deletion and recovery.
    shared = exists().where(
        Item.id == item_id,
        Item.lifecycle_state == ItemLifecycleState.active,
        ProjectItem.item_id == Item.id,
        ProjectMember.project_id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
    )
    return bool(await db.scalar(select(or_(own, shared))))


async def can_edit_item(db: AsyncSession, user: User, item_id: str) -> bool:
    item = await db.get(Item, item_id)
    if item is None or item.lifecycle_state != ItemLifecycleState.active:
        return False
    if user.role == SystemRole.administrator.value or item.created_by == user.id:
        return True
    editable = exists().where(
        ProjectItem.item_id == item_id,
        ProjectMember.project_id == ProjectItem.project_id,
        Project.id == ProjectItem.project_id,
        ProjectMember.user_id == user.id,
        ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
        Project.state == ProjectState.active,
    )
    return bool(await db.scalar(select(editable)))


async def lock_user_write_gate(db: AsyncSession, user: User) -> User:
    """Lock and refresh a User row before owner-scoped write coordination."""

    locked_user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not locked_user.active:
        raise ResourceUnavailable("user not found or inactive")
    return locked_user


async def lock_active_item(
    db: AsyncSession, item_id: str, *, message: str = "item not found"
) -> Item:
    """Acquire an active Item lifecycle gate without making an access decision."""

    item = await db.scalar(
        select(Item)
        .where(Item.id == item_id, Item.lifecycle_state == ItemLifecycleState.active)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if item is None:
        raise ResourceUnavailable(message)
    return item


async def validate_item_lifecycle_fence(
    db: AsyncSession,
    item_id: str,
    lifecycle_fence: int,
    *,
    require_active: bool = True,
) -> Item | None:
    """Validate a captured Item lifecycle fence through the Access seam.

    This is a row-locking coordination read for final workflow writes. The
    Library module remains the owner of lifecycle transitions and fence bumps.
    """

    predicates = [Item.id == item_id, Item.lifecycle_fence == lifecycle_fence]
    if require_active:
        predicates.append(Item.lifecycle_state == ItemLifecycleState.active)
    return await db.scalar(
        select(Item).where(*predicates).with_for_update().execution_options(populate_existing=True)
    )


async def lock_item_edit_authority(
    db: AsyncSession, user: User, item_id: str, *, expected_fence: int | None = None
) -> Item:
    """Lock the concrete grant path used to authorize an Item mutation.

    The User gate is always acquired first. Owners and administrators then
    lock only the Item; project grants lock one selected Project before the
    Item and are revalidated after both rows are locked.
    """

    if expected_fence is not None:
        # A fence is meaningful only for the single-item workflow seam.
        return (
            await lock_items_edit_authority(db, user, (item_id,), expected_fence=expected_fence)
        )[0]
    return (await lock_items_edit_authority(db, user, (item_id,)))[0]


async def lock_items_edit_authority(
    db: AsyncSession,
    user: User,
    item_ids: Sequence[str],
    *,
    additional_project_ids: Sequence[str] = (),
    expected_fence: int | None = None,
) -> list[Item]:
    """Lock a complete authorization path in canonical User/Project/Item order.

    The selected Project for each project-granted Item is discovered before any
    Project or Item row is locked. All required Projects (including an optional
    mutation target) and then all Items are acquired in stable ID order. The
    authorization predicates are rechecked after those locks are held.
    """

    ordered_ids = tuple(sorted(dict.fromkeys(item_ids)))
    if not ordered_ids:
        raise ResourceUnavailable("item not found")
    if expected_fence is not None and len(ordered_ids) != 1:
        raise ValueError("expected_fence requires exactly one item")

    locked_user = await db.scalar(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_user is None or not locked_user.active:
        raise ResourceUnavailable("item not found")

    owner_rows = (
        await db.execute(select(Item.id, Item.created_by).where(Item.id.in_(ordered_ids)))
    ).all()
    owners: dict[str, str] = {item_id: owner_id for item_id, owner_id in owner_rows}  # ruff: ignore[unnecessary-comprehension]
    if len(owners) != len(ordered_ids):
        raise ResourceUnavailable("item not found")

    selected_projects: dict[str, str] = {}
    if locked_user.role != SystemRole.administrator.value:
        for item_id in ordered_ids:
            if owners[item_id] == locked_user.id:
                continue
            project_id = await db.scalar(
                select(ProjectItem.project_id)
                .join(ProjectMember, ProjectMember.project_id == ProjectItem.project_id)
                .join(Project, Project.id == ProjectItem.project_id)
                .where(
                    ProjectItem.item_id == item_id,
                    ProjectMember.user_id == locked_user.id,
                    ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
                    Project.state == ProjectState.active,
                )
                .order_by(ProjectItem.project_id)
                .limit(1)
            )
            if project_id is None:
                raise ResourceUnavailable("item not found")
            selected_projects[item_id] = project_id

    project_ids = tuple(sorted(set(additional_project_ids) | set(selected_projects.values())))
    for project_id in project_ids:
        await db.scalar(
            select(Project.id)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    predicates = [Item.id.in_(ordered_ids), Item.lifecycle_state == ItemLifecycleState.active]
    if expected_fence is not None:
        predicates.append(Item.lifecycle_fence == expected_fence)
    items = list(
        (
            await db.scalars(
                select(Item)
                .where(*predicates)
                .order_by(Item.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(items) != len(ordered_ids):
        raise ResourceUnavailable("item not found")

    for item in items:
        project_id = selected_projects.get(item.id)
        if project_id is None:
            if (
                locked_user.role != SystemRole.administrator.value
                and item.created_by != locked_user.id
            ):
                raise ResourceUnavailable("item not found")
            continue
        granted = await db.scalar(
            select(ProjectMember.project_id)
            .join(ProjectItem, ProjectItem.project_id == ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == locked_user.id,
                ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
                ProjectItem.item_id == item.id,
                Project.state == ProjectState.active,
            )
        )
        if granted is None:
            raise ResourceUnavailable("item not found")
    return items


def can_delete_item(db: AsyncSession, user: User, item: Item) -> bool:
    if item.lifecycle_state != ItemLifecycleState.active:
        return False
    if user.role == SystemRole.administrator.value:
        return True
    return item.created_by == user.id


async def require_readable_item(db: AsyncSession, user: User, item_id: str) -> Item:
    if not await can_read_item(db, user, item_id):
        raise ResourceUnavailable("item not found")
    item = await db.scalar(
        select(Item)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise ResourceNotFound("item not found")
    return item


async def require_editable_item(db: AsyncSession, user: User, item_id: str) -> Item:
    await lock_item_edit_authority(db, user, item_id)
    item = await db.scalar(
        select(Item)
        .options(
            selectinload(Item.author_links).selectinload(ItemAuthor.author),
            selectinload(Item.identifier_links),
        )
        .where(Item.id == item_id)
    )
    if item is None:
        raise ResourceNotFound("item not found")
    return item


async def require_accessible_items(db: AsyncSession, user: User, item_ids: list[str]) -> list[Item]:
    requested_ids = tuple(dict.fromkeys(item_ids))
    rows = list(
        (
            await db.scalars(
                select(Item)
                .options(
                    selectinload(Item.author_links).selectinload(ItemAuthor.author),
                    selectinload(Item.identifier_links),
                )
                .where(Item.id.in_(requested_ids))
            )
        ).all()
    )
    by_id = {item.id: item for item in rows}
    selected = [by_id.get(item_id) for item_id in requested_ids]
    items = [
        item for item in selected if item is not None and await can_read_item(db, user, item.id)
    ]
    if not items or len(items) != len(selected):
        raise ValidationFailure("select one or more accessible items")
    return items
