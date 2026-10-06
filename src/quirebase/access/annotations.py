from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, false, or_, select

from quirebase.access.context import (
    ProjectContext,
    WorkspaceContext,
    require_workspace_action,
    resolve_workspace_context,
)
from quirebase.access.items import require_readable_item
from quirebase.access.project_scope import discoverable_project_ids_query, require_project_context
from quirebase.access.workspace_policy import ResourceAction, action_allowed
from quirebase.core.errors import (
    PermissionDenied,
    ProjectLifecycleError,
    ResourceUnavailable,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.models import (
    AnnotationScope,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectState,
    User,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import ColumnElement


ANNOTATION_MODERATION_ACTIONS = {
    "hide": ResourceAction.project_annotation_hide,
    "archive": ResourceAction.project_annotation_archive,
    "restore": ResourceAction.project_annotation_restore,
    "lock": ResourceAction.project_annotation_lock,
    "unlock": ResourceAction.project_annotation_unlock,
    "delete": ResourceAction.project_annotation_delete,
}


def annotation_moderation_action(action: str) -> ResourceAction:
    return ANNOTATION_MODERATION_ACTIONS[action]


def annotation_decisions(
    context: WorkspaceContext,
    annotation: PdfAnnotation,
    *,
    editable: bool,
    project_active: bool,
) -> tuple[ResourceAction, ...]:
    actions: set[ResourceAction] = set()
    scope_prefix = (
        "project_annotation"
        if annotation.scope is AnnotationScope.project
        else "private_annotation"
    )
    if editable:
        for action in ("update", "delete"):
            resource_action = ResourceAction(f"{scope_prefix}.{action}")
            if action_allowed(context, resource_action, relation="own"):
                actions.add(resource_action)

    if (
        annotation.scope is AnnotationScope.project
        and annotation.deleted_at is None
        and annotation.author_id != context.actor_id
        and project_active
    ):
        candidates = (
            ["restore"]
            if annotation.hidden_at is not None or annotation.archived_at is not None
            else ["hide", "archive"]
        )
        candidates += ["unlock"] if annotation.locked_at is not None else ["lock"]
        candidates.append("delete")
        for candidate in candidates:
            resource_action = annotation_moderation_action(candidate)
            if action_allowed(context, resource_action, relation="other"):
                actions.add(resource_action)

    return tuple(sorted(actions, key=lambda action: action.value))


def visible_annotation_scope_predicate(
    context: WorkspaceContext,
    *,
    project_item_ids: Any | None = None,
    include_private: bool = True,
    include_project: bool = True,
    relations: tuple[str, ...] = ("own", "other"),
) -> ColumnElement[bool]:
    """Build the SQL scope predicate from Casbin read decisions and caller-loaded facts."""

    def authorship_predicate(resource: str) -> ColumnElement[bool] | None:
        authorship: list[ColumnElement[bool]] = []
        read_action = ResourceAction(f"{resource}.read")
        if "own" in relations and action_allowed(context, read_action, relation="own"):
            authorship.append(PdfAnnotation.author_id == context.actor_id)
        if "other" in relations and action_allowed(context, read_action, relation="other"):
            authorship.append(PdfAnnotation.author_id != context.actor_id)
        return or_(*authorship) if authorship else None

    scopes: list[ColumnElement[bool]] = []
    private_authorship = authorship_predicate("private_annotation")
    if include_private and private_authorship is not None:
        scopes.append(and_(PdfAnnotation.scope == AnnotationScope.private, private_authorship))
    project_authorship = authorship_predicate("project_annotation")
    if include_project and project_item_ids is not None and project_authorship is not None:
        scopes.append(
            and_(
                PdfAnnotation.scope == AnnotationScope.project,
                project_authorship,
                PdfAnnotation.project_item_id.in_(project_item_ids),
            )
        )
    return or_(*scopes) if scopes else false()


async def can_edit_annotation(
    db: AsyncSession, user: User, workspace_id: str, annotation: PdfAnnotation
) -> bool:
    try:
        await _require_annotation_action(db, user, workspace_id, annotation, "update")
    except (
        PermissionDenied,
        ProjectLifecycleError,
        ResourceUnavailable,
        WorkspaceLifecycleError,
        WorkspaceMembershipRequired,
    ):
        return False
    return True


async def _annotation_project_context(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    annotation: PdfAnnotation,
    operation: ResourceAction,
    *,
    relation: str = "any",
) -> ProjectContext:
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == annotation.project_item_id,
            ProjectItem.workspace_id == workspace_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation Project not found")
    return await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        operation,
        relation=relation,
        lock="shared",
    )


async def _require_annotation_action(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    annotation: PdfAnnotation,
    action: str,
) -> None:
    if (
        annotation.workspace_id != workspace_id
        or annotation.hidden_at is not None
        or annotation.archived_at is not None
        or annotation.locked_at is not None
    ):
        raise ResourceUnavailable("Annotation not found")
    if annotation.scope is AnnotationScope.private:
        resource = "private_annotation"
    else:
        resource = "project_annotation"
    if annotation.author_id != user.id:
        raise ResourceUnavailable("Annotation not found")
    resource_action = ResourceAction(f"{resource}.{action}")
    try:
        if annotation.scope is AnnotationScope.private:
            await require_workspace_action(
                db,
                user,
                workspace_id,
                resource_action,
                relation="own",
            )
        else:
            await _annotation_project_context(
                db,
                user,
                workspace_id,
                annotation,
                resource_action,
                relation="own",
            )
    except PermissionDenied as error:
        raise ResourceUnavailable("Annotation not found") from error


async def editable_annotation_ids(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    annotations: list[PdfAnnotation],
) -> set[str]:
    candidates = [
        annotation
        for annotation in annotations
        if annotation.workspace_id == workspace_id
        and annotation.author_id == user.id
        and annotation.hidden_at is None
        and annotation.archived_at is None
        and annotation.locked_at is None
    ]
    if not candidates:
        return set()
    try:
        context = await resolve_workspace_context(db, user, workspace_id)
    except (
        PermissionDenied,
        ResourceUnavailable,
        WorkspaceLifecycleError,
        WorkspaceMembershipRequired,
    ):
        return set()
    private_allowed = action_allowed(
        context, ResourceAction.private_annotation_update, relation="own"
    )
    project_allowed = action_allowed(
        context, ResourceAction.project_annotation_update, relation="own"
    )
    project_item_ids = (
        await _active_visible_project_item_ids(
            db,
            context,
            {
                annotation.project_item_id
                for annotation in candidates
                if annotation.scope is AnnotationScope.project
                and annotation.project_item_id is not None
            },
        )
        if project_allowed
        else set()
    )
    return {
        annotation.id
        for annotation in candidates
        if (
            private_allowed
            if annotation.scope is AnnotationScope.private
            else annotation.project_item_id in project_item_ids
        )
    }


async def _active_visible_project_item_ids(
    db: AsyncSession, context: WorkspaceContext, project_item_ids: set[str]
) -> set[str]:
    """Batch Project facts for read hints; mutation paths reauthorize under locks."""

    if not project_item_ids:
        return set()
    return set(
        (
            await db.scalars(
                select(ProjectItem.id)
                .join(Project, Project.id == ProjectItem.project_id)
                .where(
                    ProjectItem.id.in_(project_item_ids),
                    ProjectItem.workspace_id == context.workspace_id,
                    Project.state == ProjectState.active,
                    Project.id.in_(discoverable_project_ids_query(context)),
                )
            )
        ).all()
    )


async def editable_annotation_reply_ids(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    replies: list[PdfAnnotationReply],
    annotations: dict[str, PdfAnnotation],
    *,
    action: str = "update",
) -> set[str]:
    if not replies:
        return set()
    candidates: list[tuple[PdfAnnotationReply, PdfAnnotation]] = []
    for reply in replies:
        annotation = annotations.get(reply.annotation_id)
        if (
            reply.workspace_id != workspace_id
            or annotation is None
            or annotation.workspace_id != workspace_id
            or annotation.hidden_at is not None
            or annotation.archived_at is not None
            or annotation.locked_at is not None
        ):
            continue
        candidates.append((reply, annotation))
    if not candidates:
        return set()
    try:
        context = await resolve_workspace_context(db, user, workspace_id)
    except (
        PermissionDenied,
        ResourceUnavailable,
        WorkspaceLifecycleError,
        WorkspaceMembershipRequired,
    ):
        return set()
    private_action = ResourceAction(f"private_annotation_reply.{action}")
    project_action = ResourceAction(f"project_annotation_reply.{action}")
    private_allowed = {
        relation: action_allowed(context, private_action, relation=relation)
        for relation in ("own", "other")
    }
    project_allowed = {
        relation: action_allowed(context, project_action, relation=relation)
        for relation in ("own", "other")
    }
    project_item_ids = await _active_visible_project_item_ids(
        db,
        context,
        {
            annotation.project_item_id
            for reply, annotation in candidates
            if annotation.scope is AnnotationScope.project
            and annotation.project_item_id is not None
            and project_allowed["own" if reply.author_id == user.id else "other"]
        },
    )
    return {
        reply.id
        for reply, annotation in candidates
        if (
            annotation.author_id == user.id
            and private_allowed["own" if reply.author_id == user.id else "other"]
            if annotation.scope is AnnotationScope.private
            else (
                annotation.project_item_id in project_item_ids
                and project_allowed["own" if reply.author_id == user.id else "other"]
            )
        )
    }


async def _visible_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    *,
    deleted: bool,
) -> PdfAnnotation:
    await require_readable_item(db, user, workspace_id, item_id)
    record = await db.scalar(
        select(PdfAnnotation).where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
        )
    )
    revision = (
        await db.scalar(
            select(FileRevision).where(
                FileRevision.id == record.file_revision_id,
                FileRevision.workspace_id == workspace_id,
                FileRevision.item_id == item_id,
            )
        )
        if record is not None
        else None
    )
    if (
        record is None
        or revision is None
        or (record.deleted_at is not None) != deleted
        or record.hidden_at is not None
        or record.archived_at is not None
    ):
        raise ResourceUnavailable("Annotation not found")
    if record.scope is AnnotationScope.private:
        private_context = await resolve_workspace_context(db, user, workspace_id)
        relation = "own" if record.author_id == private_context.actor_id else "other"
        if not action_allowed(
            private_context,
            ResourceAction.private_annotation_read,
            relation=relation,
        ):
            raise ResourceUnavailable("Annotation not found")
        return record
    project_item = await db.scalar(
        select(ProjectItem).where(
            ProjectItem.id == record.project_item_id,
            ProjectItem.workspace_id == workspace_id,
            ProjectItem.item_id == item_id,
        )
    )
    if project_item is None:
        raise ResourceUnavailable("Annotation not found")
    project_context = await require_project_context(
        db,
        user,
        workspace_id,
        project_item.project_id,
        ResourceAction.workspace_read,
    )
    relation = "own" if record.author_id == project_context.workspace.actor_id else "other"
    if not action_allowed(
        project_context.workspace,
        ResourceAction.project_annotation_read,
        relation=relation,
    ):
        raise ResourceUnavailable("Annotation not found")
    return record


async def require_visible_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    return await _visible_annotation(db, user, workspace_id, item_id, annotation_id, deleted=False)


async def require_editable_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, workspace_id, item_id, annotation_id)
    await _require_annotation_action(db, user, workspace_id, record, "update")
    return record


async def require_deletable_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    record = await require_visible_annotation(db, user, workspace_id, item_id, annotation_id)
    await _require_annotation_action(db, user, workspace_id, record, "delete")
    return record


async def require_restorable_annotation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
) -> PdfAnnotation:
    record = await _visible_annotation(db, user, workspace_id, item_id, annotation_id, deleted=True)
    if record.deleted_by_moderation:
        raise ResourceUnavailable("Annotation not found")
    await _require_annotation_action(db, user, workspace_id, record, "restore")
    return record


async def require_visible_annotation_for_reply_mutation(
    db: AsyncSession,
    user: User,
    workspace_id: str,
    item_id: str,
    annotation_id: str,
    *,
    action: str,
) -> tuple[User, PdfAnnotation]:
    """Authorize a reply write and fence every row that can revoke it until commit."""
    candidate = await require_visible_annotation(db, user, workspace_id, item_id, annotation_id)
    expected_scope = candidate.scope
    expected_project_item_id = candidate.project_item_id
    project_item = None
    if expected_scope is AnnotationScope.project:
        if expected_project_item_id is None:
            raise ResourceUnavailable("Annotation not found")
        project_item = await db.scalar(
            select(ProjectItem).where(
                ProjectItem.id == expected_project_item_id,
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.item_id == item_id,
            )
        )
        if project_item is None:
            raise ResourceUnavailable("Annotation not found")

    resource_action = ResourceAction(f"{expected_scope.value}_annotation_reply.{action}")
    relation = "other" if action == "create" and candidate.author_id != user.id else "own"
    # Match governance's root-to-child lock order. A read gate would leave the
    # roots unlocked until after child locks, deadlocking with root deletion.
    try:
        if project_item is None:
            context = await require_workspace_action(
                db, user, workspace_id, resource_action, relation=relation
            )
            locked_user = context.actor
        else:
            project_context = await require_project_context(
                db,
                user,
                workspace_id,
                project_item.project_id,
                resource_action,
                relation=relation,
                lock="shared",
            )
            locked_user = project_context.workspace.actor
    except PermissionDenied as error:
        if action == "create":
            raise
        operation = "restored" if action == "restore" else "edited"
        raise ResourceUnavailable(f"annotation reply not found or cannot be {operation}") from error

    if project_item is not None:
        locked_project_item = await db.scalar(
            select(ProjectItem)
            .where(
                ProjectItem.id == expected_project_item_id,
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == project_item.project_id,
                ProjectItem.item_id == item_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update(read=True)
        )
        if locked_project_item is None:
            raise ResourceUnavailable("Annotation not found")
    record = await db.scalar(
        select(PdfAnnotation)
        .where(
            PdfAnnotation.id == annotation_id,
            PdfAnnotation.workspace_id == workspace_id,
            PdfAnnotation.deleted_at.is_(None),
            PdfAnnotation.hidden_at.is_(None),
            PdfAnnotation.archived_at.is_(None),
        )
        .execution_options(populate_existing=True)
        .with_for_update(read=True)
    )
    if (
        record is None
        or record.item_id != item_id
        or record.scope is not expected_scope
        or record.project_item_id != expected_project_item_id
        or (record.scope is AnnotationScope.private and record.author_id != locked_user.id)
    ):
        raise ResourceUnavailable("Annotation not found")
    if record.locked_at is not None:
        raise PermissionDenied("Annotation is locked")
    return locked_user, record
