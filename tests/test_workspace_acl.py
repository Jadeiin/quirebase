from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import (
    Capability,
    effective_capabilities,
    get_item,
    require,
    require_project_context,
    require_workspace_capability,
    resolve_workspace_context,
    workspace_select,
)
from quirebase.access.annotations import can_edit_annotation, editable_annotation_reply_ids
from quirebase.core.config import get_settings
from quirebase.core.errors import (
    PermissionDenied,
    ResourceNotFound,
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.core.workflows import WorkflowSummary
from quirebase.documents import (
    get_export_file,
    get_export_status,
    list_document_annotations,
    moderate_document_annotation,
    review_item_annotations,
)
from quirebase.documents.annotations import (
    create_annotation_reply,
    delete_annotation_reply,
    delete_document_annotation,
    restore_annotation_reply,
    restore_document_annotation,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.documents.bundles import _own_annotations
from quirebase.documents.revisions import delete_attachment, get_pdf_viewer_data
from quirebase.documents.schemas import (
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationUpdate,
)
from quirebase.documents.workflows import (
    ANNOTATION_EXPORT_WORKFLOW,
    delete_unreferenced_objects_step,
)
from quirebase.library import (
    ItemSection,
    add_discussion_message,
    add_project_discussion_message,
    copy_item_to_workspace,
    get_dashboard_data,
    list_project_discussion_messages,
    moderate_discussion_message,
    moderate_project_discussion_message,
    open_item_section,
    search_library,
)
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    Attachment,
    AuditEvent,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    ItemTag,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    SystemSetting,
    Tag,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.operations import dispatch_workspace_reindex
from quirebase.projects import (
    ProjectMemberConflict,
    add_item_to_project,
    add_project_member,
    create_project,
    delete_project,
    get_project,
    get_project_item,
    join_project,
    leave_project,
    list_workspace_projects,
    open_project_workspace,
    remove_item_from_project,
    remove_project_member,
    require_project,
    set_project_state,
    update_project_settings,
)
from quirebase.search import search_index
from quirebase.web.api.library_schemas import discussion_message_view
from quirebase.web.api.workflows import workflow_status
from quirebase.workspaces import (
    accept_workspace_invitation,
    archive_workspace,
    create_workspace,
    invite_workspace_member,
    list_workspace_governance_members,
    list_workspace_members,
    permanently_delete_workspace,
    read_workspace_items_break_glass,
    recover_workspace_governance,
    set_workspace_member_role,
    suspend_workspace_governance,
    suspend_workspace_member,
    terminate_workspace_member,
    transfer_workspace_ownership,
)
from quirebase.workspaces.workflows import cleanup_deleted_workspace_objects_step


def test_effective_capabilities_follow_workspace_lifecycle():
    active = effective_capabilities(WorkspaceRole.owner, WorkspaceState.active)
    archived = effective_capabilities(WorkspaceRole.owner, WorkspaceState.archived)
    governance_suspended = effective_capabilities(
        WorkspaceRole.admin, WorkspaceState.active, governance_suspended=True
    )

    assert Capability.items_create in active
    assert Capability.workspace_delete in active
    assert Capability.projects_create in active
    assert Capability.projects_create_managed in active
    assert Capability.workspace_read in archived
    assert Capability.workspace_archive in archived
    assert Capability.workspace_delete in archived
    assert Capability.projects_create_managed not in archived
    assert Capability.items_create not in archived
    assert Capability.projects_create in effective_capabilities(
        WorkspaceRole.editor, WorkspaceState.active
    )
    assert Capability.projects_create_managed not in effective_capabilities(
        WorkspaceRole.editor, WorkspaceState.active
    )
    assert Capability.projects_create_managed in effective_capabilities(
        WorkspaceRole.admin, WorkspaceState.active
    )
    assert Capability.projects_create_managed not in effective_capabilities(
        WorkspaceRole.reviewer, WorkspaceState.active
    )
    assert Capability.projects_create_managed not in effective_capabilities(
        WorkspaceRole.viewer, WorkspaceState.active
    )
    assert governance_suspended == frozenset({
        Capability.workspace_read,
        Capability.workspace_export,
    })


@pytest.mark.anyio
async def test_workspace_member_directory_and_governance_projections(async_db):
    owner = await _user(async_db, "member-projection-owner")
    active = await _user(async_db, "member-projection-active")
    suspended = await _user(async_db, "member-projection-suspended")
    workspace_id = fixture_workspace_id(owner)
    async_db.add_all([
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=active.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        ),
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=suspended.id,
            role=WorkspaceRole.reviewer,
            state=WorkspaceMemberState.suspended,
            invited_by=owner.id,
        ),
    ])
    await async_db.commit()

    directory = await list_workspace_members(async_db, active, workspace_id)
    assert {member.user_id for member in directory} == {owner.id, active.id}

    governance = await list_workspace_governance_members(async_db, owner, workspace_id)
    assert {member.user_id for member in governance} == {owner.id, active.id, suspended.id}
    with pytest.raises(PermissionDenied):
        await list_workspace_governance_members(async_db, active, workspace_id)


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


async def _shared_annotation_context(db, name: str):
    author = await _user(db, f"{name}-author")
    viewer = await _user(db, f"{name}-viewer")
    workspace_id = fixture_workspace_id(author)
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=viewer.id,
            role=WorkspaceRole.viewer,
            invited_by=author.id,
        )
    )
    item = Item(workspace_id=workspace_id, title=name, created_by=author.id)
    project = Project(
        workspace_id=workspace_id,
        name=name,
        created_by=author.id,
    )
    db.add_all([item, project])
    await db.flush()
    project_item = ProjectItem(
        workspace_id=workspace_id, project_id=project.id, item_id=item.id, added_by=author.id
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key=f"objects/{name}.pdf",
        size=1,
        original_name=f"{name}.pdf",
        created_by=author.id,
    )
    db.add_all([project_item, revision])
    await db.flush()
    annotation = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        body="Shared note",
        payload={"type": "note", "rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
    )
    db.add(annotation)
    await db.flush()
    reply = PdfAnnotationReply(
        workspace_id=workspace_id,
        annotation_id=annotation.id,
        author_id=author.id,
        body="Shared reply",
    )
    db.add(reply)
    await db.commit()
    return author, viewer, item, project, revision, annotation, reply


@pytest.mark.anyio
async def test_annotation_editability_helpers_hide_missing_workspace_membership(async_db):
    (
        author,
        _viewer,
        _item,
        _project,
        _revision,
        annotation,
        reply,
    ) = await _shared_annotation_context(async_db, "annotation-editability-membership")
    workspace_id = fixture_workspace_id(author)
    membership = await async_db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == author.id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    assert membership is not None
    membership.state = "suspended"
    await async_db.commit()

    assert not await can_edit_annotation(async_db, author, workspace_id, annotation)
    assert (
        await editable_annotation_reply_ids(
            async_db, author, workspace_id, [reply], {annotation.id: annotation}
        )
        == set()
    )


@pytest.mark.anyio
async def test_workspace_provisioning_cannot_be_repeated_for_one_user(async_db):
    user = await _user(async_db, "provisioned")
    workspace_id = fixture_workspace_id(user)

    with pytest.raises(ValidationFailure, match="only available during User creation"):
        await provision_initial_workspace(async_db, user)
    assert (
        len(
            (
                await async_db.scalars(
                    WorkspaceMember.__table__.select().where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.user_id == user.id,
                    )
                )
            ).all()
        )
        == 1
    )


@pytest.mark.anyio
async def test_ownership_transfer_does_not_prevent_another_workspace(async_db):
    first_owner = await _user(async_db, "former-workspace-owner")
    successor = await _user(async_db, "new-workspace-owner")
    workspace_id = fixture_workspace_id(first_owner)
    successor_membership = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=successor.id,
        role=WorkspaceRole.editor,
        invited_by=first_owner.id,
    )
    async_db.add(successor_membership)
    await async_db.commit()
    await transfer_workspace_ownership(async_db, first_owner, workspace_id, successor_membership.id)

    with pytest.raises(ValidationFailure, match="only available during User creation"):
        await provision_initial_workspace(async_db, first_owner)
    async_db.add(SystemSetting(key="workspace_creation_policy", value="members_allowed"))
    await async_db.commit()
    additional = await create_workspace(async_db, first_owner, "New research space")
    assert additional.owner_id == first_owner.id
    assert additional.id != workspace_id
    assert fixture_workspace_id(first_owner) == workspace_id


@pytest.mark.anyio
async def test_workspace_creation_allows_user_without_an_existing_workspace(async_db):
    user = User(username="unprovisioned-creator", password_hash="unused")
    async_db.add(user)
    async_db.add(SystemSetting(key="workspace_creation_policy", value="members_allowed"))
    await async_db.commit()

    workspace = await create_workspace(async_db, user, "Explicitly created space")
    assert workspace.owner_id == user.id


@pytest.mark.anyio
async def test_invitation_acceptance_rechecks_user_status(async_db, async_session_factory):
    owner = await _user(async_db, "invitation-status-owner")
    invitee = await _user(async_db, "invitation-status-invitee")
    workspace_id = fixture_workspace_id(owner)
    _invitation, token = await invite_workspace_member(
        async_db,
        owner,
        workspace_id,
        invitee.id,
        WorkspaceRole.viewer,
    )

    async with async_session_factory() as status_db:
        current_invitee = await status_db.get(User, invitee.id)
        assert current_invitee is not None
        current_invitee.active = False
        await status_db.commit()

    with pytest.raises(ResourceNotFound, match="invitation"):
        await accept_workspace_invitation(async_db, invitee, workspace_id, token)
    assert (
        await async_db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == invitee.id,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
        is None
    )


@pytest.mark.anyio
async def test_invitation_creation_rechecks_user_status(async_db, async_session_factory):
    owner = await _user(async_db, "invitation-create-status-owner")
    invitee = await _user(async_db, "invitation-create-status-invitee")
    workspace_id = fixture_workspace_id(owner)

    # Match the HTTP handler, which resolves the target User before entering
    # the service and therefore leaves a stale identity-map entry behind.
    assert await async_db.get(User, invitee.id) is invitee
    async with async_session_factory() as status_db:
        current_invitee = await status_db.get(User, invitee.id)
        assert current_invitee is not None
        current_invitee.active = False
        await status_db.commit()

    with pytest.raises(ValidationFailure, match="existing active User"):
        await invite_workspace_member(
            async_db,
            owner,
            workspace_id,
            invitee.id,
            WorkspaceRole.viewer,
        )
    assert (
        await async_db.scalar(
            select(WorkspaceInvitation.id).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.user_id == invitee.id,
            )
        )
        is None
    )


@pytest.mark.anyio
@pytest.mark.parametrize("membership_action", ["suspend", "terminate"])
async def test_old_workspace_invitations_cannot_restore_access(async_db, membership_action):
    owner = await _user(async_db, f"stale-invitation-{membership_action}-owner")
    invitee = await _user(async_db, f"stale-invitation-{membership_action}-invitee")
    workspace_id = fixture_workspace_id(owner)
    _first, first_token = await invite_workspace_member(
        async_db, owner, workspace_id, invitee.id, WorkspaceRole.viewer
    )
    second, second_token = await invite_workspace_member(
        async_db, owner, workspace_id, invitee.id, WorkspaceRole.editor
    )
    member = await accept_workspace_invitation(async_db, invitee, workspace_id, first_token)
    assert (await async_db.get(WorkspaceInvitation, second.id)).revoked_at is not None

    # Cover a pending token left by an interrupted or older admission transaction.
    second.revoked_at = None
    await async_db.commit()
    if membership_action == "suspend":
        await suspend_workspace_member(async_db, owner, workspace_id, member.id)
    else:
        await terminate_workspace_member(async_db, owner, workspace_id, member.id)
    assert (await async_db.get(WorkspaceInvitation, second.id)).revoked_at is not None
    with pytest.raises(ResourceNotFound, match="invitation"):
        await accept_workspace_invitation(async_db, invitee, workspace_id, second_token)
    with pytest.raises(WorkspaceMembershipRequired):
        await require_workspace_capability(
            async_db, invitee, workspace_id, Capability.workspace_read
        )

    if membership_action == "terminate":
        _new, new_token = await invite_workspace_member(
            async_db, owner, workspace_id, invitee.id, WorkspaceRole.viewer
        )
        replacement = await accept_workspace_invitation(async_db, invitee, workspace_id, new_token)
        assert replacement.id != member.id


@pytest.mark.anyio
async def test_pdf_viewer_hides_managed_project_contexts_from_nonmembers(async_db):
    (
        owner,
        viewer,
        item,
        workspace_project,
        revision,
        _annotation,
        _reply,
    ) = await _shared_annotation_context(async_db, "pdf-visible-projects")
    managed_project = Project(
        workspace_id=item.workspace_id,
        name="Managed participation",
        created_by=owner.id,
        visibility=ProjectVisibility.managed,
    )
    async_db.add(managed_project)
    await async_db.flush()
    async_db.add_all([
        ProjectItem(
            workspace_id=item.workspace_id,
            project_id=managed_project.id,
            item_id=item.id,
            added_by=owner.id,
        ),
    ])
    await async_db.commit()

    async def project_ids():
        data = await get_pdf_viewer_data(async_db, viewer, item.workspace_id, item.id, revision.id)
        return {project.id for project in data["projects"]}

    assert await project_ids() == {workspace_project.id}
    async_db.add(
        ProjectMember(
            workspace_id=item.workspace_id,
            project_id=managed_project.id,
            user_id=viewer.id,
        )
    )
    await async_db.commit()
    assert await project_ids() == {workspace_project.id, managed_project.id}


@pytest.mark.anyio
async def test_workflow_status_is_visible_only_to_its_actor(async_db, fake_durable_operations):
    owner = await _user(async_db, "workflow-status-owner")
    viewer = await _user(async_db, "workflow-status-viewer")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(workspace_id=workspace_id, user_id=viewer.id, role=WorkspaceRole.viewer)
    )
    await async_db.commit()
    await fake_durable_operations.enqueue(
        "test.workflow",
        queue_name="test",
        workflow_id="test-workflow-status",
        attributes={"workspace_id": workspace_id, "actor_id": owner.id},
    )
    assert (await workflow_status(workspace_id, "test-workflow-status", owner, async_db))[
        "state"
    ] == "pending"
    with pytest.raises(ResourceNotFound, match="workflow"):
        await workflow_status(workspace_id, "test-workflow-status", viewer, async_db)


@pytest.mark.anyio
async def test_admins_only_workspace_creation_requires_explicit_owner_username(async_db):
    administrator = await _user(async_db, "workspace-creator-admin")
    administrator.role = "administrator"
    initial_owner = await _user(async_db, "workspace-assigned-owner")
    await async_db.commit()

    with pytest.raises(PermissionDenied):
        await create_workspace(
            async_db,
            initial_owner,
            "Unauthorized",
            owner_username=initial_owner.username,
        )
    with pytest.raises(ValidationFailure, match="owner_username is required"):
        await create_workspace(async_db, administrator, "Missing owner")

    created_by_admin = await create_workspace(
        async_db,
        administrator,
        "Creator-owned",
        owner_username=administrator.username,
    )
    assert created_by_admin.owner_id == administrator.id
    assert created_by_admin.created_by == administrator.id

    created = await create_workspace(
        async_db,
        administrator,
        "Admin-created",
        owner_username=initial_owner.username,
    )
    assert created.owner_id == initial_owner.id
    assert created.created_by == administrator.id
    assert (
        await async_db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == created.id,
                WorkspaceMember.user_id == administrator.id,
            )
        )
        is None
    )

    assert (
        await async_db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == created_by_admin.id,
                WorkspaceMember.user_id == administrator.id,
            )
        )
        is not None
    )


@pytest.mark.anyio
async def test_workspace_delete_waits_for_retention_and_purges_owned_data(
    async_db, async_session_factory, fake_durable_operations, monkeypatch
):
    owner = await _user(async_db, "purge-owner")
    workspace_id = fixture_workspace_id(owner)
    item = Item(workspace_id=workspace_id, title="Purged search term", created_by=owner.id)
    project = Project(
        workspace_id=workspace_id,
        name="Purged Project",
        created_by=owner.id,
    )
    tag = Tag(
        workspace_id=workspace_id,
        name="Purged Tag",
        normalized_name="purged tag",
        created_by=owner.id,
    )
    async_db.add_all([item, project, tag])
    await async_db.flush()
    revision_object = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-purge-revision", max_bytes=1024
    )
    attachment_object = await get_object_store().put_object(
        uuid4(), ObjectSuffix.BINARY, b"purge-attachment", max_bytes=1024
    )
    staged_object = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-purge-staged", max_bytes=1024
    )
    export_object = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-purge-export", max_bytes=1024
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key=revision_object.key,
        size=revision_object.size,
        original_name="purge.pdf",
        created_by=owner.id,
    )
    async_db.add(revision)
    await async_db.flush()
    annotation = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=owner.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
        payload={},
    )
    async_db.add(annotation)
    await async_db.flush()
    reply = PdfAnnotationReply(
        workspace_id=workspace_id,
        annotation_id=annotation.id,
        author_id=owner.id,
        body="Purged reply",
    )
    async_db.add_all([
        ProjectItem(
            workspace_id=workspace_id,
            project_id=project.id,
            item_id=item.id,
            added_by=owner.id,
        ),
        ItemTag(workspace_id=workspace_id, item_id=item.id, tag_id=tag.id),
        Attachment(
            workspace_id=workspace_id,
            item_id=item.id,
            object_key=attachment_object.key,
            size=attachment_object.size,
            original_name="attachment.bin",
            created_by=owner.id,
        ),
        ImportBatch(
            workspace_id=workspace_id,
            actor_id=owner.id,
            file_format="pdf",
            records=json.dumps([{"_pdf": {"object_key": staged_object.key}}]),
            errors="[]",
        ),
        ExportArtifact(
            workflow_id=f"export:{uuid4()}",
            workspace_id=workspace_id,
            object_key=export_object.key,
            filename="export.pdf",
            size=export_object.size,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        ),
        reply,
    ])
    await search_index(async_db).index_item(async_db, item.id)
    await async_db.commit()
    item_id, project_id, tag_id = item.id, project.id, tag.id
    annotation_ids = (annotation.id, reply.id)

    await archive_workspace(async_db, owner, workspace_id)
    with pytest.raises(WorkspaceLifecycleError, match="retention"):
        await permanently_delete_workspace(async_db, owner, workspace_id)
    assert await async_db.get(Item, item_id) is not None
    await async_db.rollback()
    workspace = await async_db.get(Workspace, workspace_id)
    assert workspace is not None
    workspace.archived_at = datetime.now(UTC) - timedelta(
        days=get_settings().workspace_delete_retention_days + 1
    )
    await async_db.commit()

    monkeypatch.setattr("quirebase.workspaces.workflows.AsyncSessionLocal", async_session_factory)
    await permanently_delete_workspace(async_db, owner, workspace_id)
    async with async_session_factory() as check_db:
        assert await check_db.get(Workspace, workspace_id) is None
        assert await check_db.get(Item, item_id) is None
        assert await check_db.get(Project, project_id) is None
        assert await check_db.get(Tag, tag_id) is None
        assert (
            await check_db.scalars(
                select(PdfAnnotationObject.id).where(PdfAnnotationObject.id.in_(annotation_ids))
            )
        ).all() == []
        deletion_event = await check_db.scalar(
            select(AuditEvent).where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.action == "workspace.delete",
            )
        )
        assert deletion_event is not None
        assert await search_index(check_db).search(check_db, "Purged") == []

    cleanup = fake_durable_operations.enqueues[-1]
    assert cleanup["workflow_name"] == "workspaces.cleanup_deleted_objects"
    assert set(cleanup["attributes"]["object_keys"]) == {
        revision_object.key,
        attachment_object.key,
        staged_object.key,
        export_object.key,
    }
    deleted = await cleanup_deleted_workspace_objects_step(
        cleanup["workflow_id"], owner.id, workspace_id, cleanup["attributes"]["object_keys"]
    )
    assert set(deleted) == set(cleanup["attributes"]["object_keys"])
    for key in deleted:
        assert not await get_object_store().exists(key)
    async_db.add(SystemSetting(key="workspace_creation_policy", value="members_allowed"))
    await async_db.commit()
    replacement = await create_workspace(async_db, owner, "Replacement workspace")
    assert replacement.id != workspace_id


@pytest.mark.anyio
async def test_workspace_object_cleanup_requires_committed_deletion(
    async_db, async_session_factory, monkeypatch
):
    owner = await _user(async_db, "cleanup-guard-owner")
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.BINARY, b"protected-object", max_bytes=1024
    )
    monkeypatch.setattr("quirebase.workspaces.workflows.AsyncSessionLocal", async_session_factory)
    with pytest.raises(ValueError, match="has not committed"):
        await cleanup_deleted_workspace_objects_step(
            "untrusted-workflow", owner.id, fixture_workspace_id(owner), [stored.key]
        )
    assert await get_object_store().exists(stored.key)


@pytest.mark.anyio
async def test_workspace_context_and_lineage_query_are_explicit(async_db):
    owner = await _user(async_db, "context-owner")
    other = await _user(async_db, "context-other")
    workspace_id = fixture_workspace_id(owner)
    context = await resolve_workspace_context(async_db, owner, workspace_id)

    assert context.actor_id == owner.id
    assert context.workspace_id == workspace_id
    assert Capability.items_edit in context.capabilities
    require(context, Capability.items_edit)

    item = Item(workspace_id=workspace_id, title="Scoped", created_by=owner.id)
    foreign = Item(workspace_id=fixture_workspace_id(other), title="Foreign", created_by=other.id)
    async_db.add_all([item, foreign])
    await async_db.commit()

    statement = workspace_select(Item, context).where(Item.id.in_([item.id, foreign.id]))
    assert [row.id for row in (await async_db.scalars(statement)).all()] == [item.id]
    assert await get_item(async_db, context, foreign.id) is None


@pytest.mark.anyio
async def test_managed_project_loaders_require_participation_or_workspace_governance(async_db):
    owner = await _user(async_db, "loader-owner")
    outsider = await _user(async_db, "loader-outsider")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=outsider.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db,
        owner,
        fixture_workspace_id(owner),
        "Members only",
        ProjectVisibility.managed,
    )
    context = await resolve_workspace_context(async_db, outsider, fixture_workspace_id(owner))
    assert await get_project(async_db, context, project.id) is None
    with pytest.raises(ResourceUnavailable, match="Project not found"):
        await require_project(async_db, context, project.id)

    owner_context = await resolve_workspace_context(async_db, owner, fixture_workspace_id(owner))
    assert await get_project(async_db, owner_context, project.id) is not None
    assert (await require_project(async_db, owner_context, project.id)).project.id == project.id
    await add_project_member(
        async_db, owner, fixture_workspace_id(owner), project.id, outsider.username
    )
    assert await get_project(async_db, context, project.id) is not None
    assert (await require_project(async_db, context, project.id)).project.id == project.id
    assert await get_project_item(async_db, owner_context, "missing") is None


@pytest.mark.anyio
async def test_workspace_roles_are_the_only_item_authority(async_db):
    owner = await _user(async_db, "owner")
    viewer = await _user(async_db, "viewer")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=viewer.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    await async_db.commit()

    await require_workspace_capability(
        async_db, viewer, fixture_workspace_id(owner), Capability.workspace_read
    )
    with pytest.raises(PermissionDenied):
        await require_workspace_capability(
            async_db, viewer, fixture_workspace_id(owner), Capability.items_edit
        )


@pytest.mark.anyio
async def test_workspace_authorization_refreshes_cached_membership(async_session_factory):
    async with async_session_factory() as db:
        owner = await _user(db, "refresh-owner")
        editor = await _user(db, "refresh-editor")
        workspace_id = fixture_workspace_id(owner)
        membership = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
        db.add(membership)
        await db.commit()
        owner_id, editor_id, membership_id = owner.id, editor.id, membership.id

    async with async_session_factory() as stale_db:
        cached_actor = await stale_db.get(User, editor_id)
        assert cached_actor is not None
        await require_workspace_capability(
            stale_db, cached_actor, workspace_id, Capability.items_edit
        )
        await stale_db.commit()

        async with async_session_factory() as governor_db:
            governor = await governor_db.get(User, owner_id)
            assert governor is not None
            await set_workspace_member_role(
                governor_db, governor, workspace_id, membership_id, WorkspaceRole.viewer
            )

        with pytest.raises(PermissionDenied):
            await require_workspace_capability(
                stale_db, cached_actor, workspace_id, Capability.items_edit
            )


@pytest.mark.anyio
async def test_managed_project_is_visible_only_to_members_and_workspace_governors(async_db):
    owner = await _user(async_db, "project-owner")
    outsider = await _user(async_db, "project-outsider")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=outsider.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    editor_capabilities = effective_capabilities(WorkspaceRole.editor, WorkspaceState.active)
    assert Capability.projects_create in editor_capabilities
    assert Capability.projects_create_managed not in editor_capabilities
    with pytest.raises(PermissionDenied):
        await create_project(
            async_db,
            outsider,
            fixture_workspace_id(owner),
            "Editor cannot create managed Projects",
            ProjectVisibility.managed,
        )
    project = await create_project(
        async_db,
        owner,
        fixture_workspace_id(owner),
        "Scoped",
        ProjectVisibility.managed,
    )
    assert [
        row[0].id
        for row in await list_workspace_projects(async_db, owner, fixture_workspace_id(owner))
    ] == [project.id]
    assert await list_workspace_projects(async_db, outsider, fixture_workspace_id(owner)) == []

    with pytest.raises(ResourceUnavailable, match="Project not found"):
        await require_project_context(
            async_db,
            outsider,
            fixture_workspace_id(owner),
            project.id,
            Capability.workspace_read,
        )
    owner_context = await require_project_context(
        async_db, owner, fixture_workspace_id(owner), project.id, Capability.workspace_read
    )
    assert owner_context.project.id == project.id
    await add_project_member(
        async_db, owner, fixture_workspace_id(owner), project.id, outsider.username
    )
    assert [
        row[0].id
        for row in await list_workspace_projects(async_db, outsider, fixture_workspace_id(owner))
    ] == [project.id]
    member_context = await require_project_context(
        async_db, outsider, fixture_workspace_id(owner), project.id, Capability.workspace_read
    )
    assert member_context.project.id == project.id
    with pytest.raises(PermissionDenied):
        await update_project_settings(
            async_db,
            outsider,
            fixture_workspace_id(owner),
            project.id,
            name=project.name,
            description=project.description,
            visibility=ProjectVisibility.open,
        )


@pytest.mark.anyio
async def test_managed_project_mutations_use_workspace_capabilities(async_db):
    owner = await _user(async_db, "managed-mutation-owner")
    editor = await _user(async_db, "managed-mutation-editor")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db, owner, workspace_id, "Managed editor mutations", ProjectVisibility.managed
    )
    item = Item(workspace_id=workspace_id, title="Managed mutation Item", created_by=owner.id)
    async_db.add(item)
    await async_db.commit()
    assert await list_workspace_projects(async_db, editor, workspace_id) == []

    await update_project_settings(
        async_db,
        editor,
        workspace_id,
        project.id,
        name="Managed editor mutations renamed",
        description=project.description,
        visibility=ProjectVisibility.managed,
    )
    await add_item_to_project(async_db, editor, workspace_id, project.id, item.id)
    assert (
        await async_db.scalar(
            select(ProjectItem.id).where(
                ProjectItem.project_id == project.id,
                ProjectItem.item_id == item.id,
            )
        )
        is not None
    )
    await remove_item_from_project(async_db, editor, workspace_id, project.id, item.id)
    assert (
        await async_db.scalar(
            select(ProjectItem.id).where(
                ProjectItem.project_id == project.id,
                ProjectItem.item_id == item.id,
            )
        )
        is None
    )


@pytest.mark.anyio
@pytest.mark.parametrize("read_only_mode", ["archived", "governance_suspended"])
async def test_open_project_participation_rejects_read_only_workspaces(async_db, read_only_mode):
    owner = await _user(async_db, "open-lifecycle-owner")
    editor = await _user(async_db, "open-lifecycle-editor")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db, owner, workspace_id, "Open lifecycle", ProjectVisibility.open
    )
    workspace = await async_db.get(Workspace, workspace_id)
    assert workspace is not None

    if read_only_mode == "archived":
        workspace.state = WorkspaceState.archived
    else:
        workspace.governance_suspended_at = datetime.now(UTC)
        workspace.governance_suspended_by = owner.id
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await join_project(async_db, editor, workspace_id, project.id)
    with pytest.raises(WorkspaceLifecycleError):
        await leave_project(async_db, owner, workspace_id, project.id)
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
        is None
    )
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == owner.id,
            )
        )
        is not None
    )


@pytest.mark.anyio
async def test_dashboard_includes_managed_projects_for_workspace_governors(async_db):
    owner = await _user(async_db, "dashboard-managed-owner")
    workspace_id = fixture_workspace_id(owner)
    project = await create_project(
        async_db, owner, workspace_id, "Governor dashboard", ProjectVisibility.managed
    )

    dashboard = await get_dashboard_data(async_db, owner, workspace_id)

    assert [row.id for row in dashboard["projects"]] == [project.id]


@pytest.mark.anyio
async def test_project_filtered_library_search_obeys_project_visibility(async_db):
    owner = await _user(async_db, "search-scope-owner")
    outsider = await _user(async_db, "search-scope-outsider")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=outsider.id,
            role=WorkspaceRole.viewer,
            invited_by=owner.id,
        )
    )
    item = Item(workspace_id=workspace_id, title="Visible library Item", created_by=owner.id)
    async_db.add(item)
    await async_db.commit()
    project = await create_project(
        async_db, owner, workspace_id, "Restricted working set", ProjectVisibility.managed
    )
    await add_item_to_project(async_db, owner, workspace_id, project.id, item.id)

    library_items, *_ = await search_library(async_db, outsider, workspace_id)
    assert item.id in {row.id for row in library_items}
    with pytest.raises(ResourceUnavailable, match="Project not found"):
        await search_library(async_db, outsider, workspace_id, project=project.id)
    await add_project_member(async_db, owner, workspace_id, project.id, outsider.username)
    outsider_scoped_items, *_ = await search_library(
        async_db, outsider, workspace_id, project=project.id
    )
    assert [row.id for row in outsider_scoped_items] == [item.id]
    scoped_items, *_ = await search_library(async_db, owner, workspace_id, project=project.id)
    assert [row.id for row in scoped_items] == [item.id]


@pytest.mark.anyio
async def test_project_discussion_uses_visibility_and_workspace_capabilities(async_db):
    owner = await _user(async_db, "discussion-owner")
    reviewer = await _user(async_db, "discussion-reviewer")
    outsider = await _user(async_db, "discussion-outsider")
    async_db.add_all([
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=reviewer.id,
            role=WorkspaceRole.reviewer,
            invited_by=owner.id,
        ),
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=outsider.id,
            role=WorkspaceRole.reviewer,
            invited_by=owner.id,
        ),
    ])
    await async_db.commit()
    project = await create_project(
        async_db,
        owner,
        fixture_workspace_id(owner),
        "Discussion scope",
        ProjectVisibility.managed,
    )
    async_db.add(
        ProjectMember(
            workspace_id=fixture_workspace_id(owner),
            project_id=project.id,
            user_id=reviewer.id,
        )
    )
    await async_db.commit()

    with pytest.raises(ResourceUnavailable, match="Project not found"):
        await add_project_discussion_message(
            async_db,
            outsider,
            fixture_workspace_id(owner),
            project.id,
            "Unauthorized note",
        )
    message = await add_project_discussion_message(
        async_db,
        reviewer,
        fixture_workspace_id(owner),
        project.id,
        "Review note",
    )
    assert message.project_id == project.id
    assert [
        row.id
        for row in await list_project_discussion_messages(
            async_db, reviewer, fixture_workspace_id(owner), project.id
        )
    ] == [message.id]
    with pytest.raises(ResourceUnavailable, match="Project not found"):
        await list_project_discussion_messages(
            async_db, outsider, fixture_workspace_id(owner), project.id
        )


@pytest.mark.anyio
async def test_discussion_moderation_is_workspace_governance_with_audited_reason(async_db):
    owner = await _user(async_db, "discussion-moderator-owner")
    admin = await _user(async_db, "discussion-moderator-admin")
    editor = await _user(async_db, "discussion-moderator-editor")
    author = await _user(async_db, "discussion-moderator-author")
    instance_admin = await _user(async_db, "discussion-instance-admin")
    instance_admin.role = "administrator"
    workspace_id = fixture_workspace_id(owner)
    async_db.add_all([
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=admin.id,
            role=WorkspaceRole.admin,
            invited_by=owner.id,
        ),
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        ),
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=author.id,
            role=WorkspaceRole.reviewer,
            invited_by=owner.id,
        ),
    ])
    item = Item(workspace_id=workspace_id, title="Moderated Item", created_by=owner.id)
    async_db.add(item)
    await async_db.commit()
    message = await add_discussion_message(
        async_db, author, workspace_id, item.id, "Needs moderation"
    )
    message.author = author
    owner_context = await resolve_workspace_context(async_db, owner, workspace_id)
    author_context = await resolve_workspace_context(async_db, author, workspace_id)
    assert discussion_message_view(message, owner_context).allowed_actions == ["moderate"]
    assert discussion_message_view(message, author_context).allowed_actions == ["delete"]
    assert discussion_message_view(message, owner_context, writable=False).allowed_actions == []

    assert (
        Capability.discussion_moderate
        in (await resolve_workspace_context(async_db, owner, workspace_id)).capabilities
    )
    assert (
        Capability.discussion_moderate
        in (await resolve_workspace_context(async_db, admin, workspace_id)).capabilities
    )
    assert (
        Capability.discussion_moderate
        not in (await resolve_workspace_context(async_db, editor, workspace_id)).capabilities
    )
    with pytest.raises(PermissionDenied):
        await moderate_discussion_message(
            async_db, editor, workspace_id, item.id, message.id, "Policy"
        )
    assert item.id in {
        row.id
        for row in await read_workspace_items_break_glass(
            async_db, instance_admin, workspace_id, "Investigating policy violation"
        )
    }
    with pytest.raises(WorkspaceMembershipRequired):
        await moderate_discussion_message(
            async_db, instance_admin, workspace_id, item.id, message.id, "Break-glass"
        )
    with pytest.raises(ResourceUnavailable):
        await moderate_discussion_message(
            async_db, admin, fixture_workspace_id(admin), item.id, message.id, "Wrong Workspace"
        )
    with pytest.raises(ValidationFailure):
        await moderate_discussion_message(async_db, admin, workspace_id, item.id, message.id, "  ")
    await moderate_discussion_message(
        async_db, admin, workspace_id, item.id, message.id, "Policy violation"
    )
    with pytest.raises(ResourceUnavailable):
        await moderate_discussion_message(
            async_db, admin, workspace_id, item.id, message.id, "Retry"
        )
    assert await async_db.get(type(message), message.id) is None
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.target_id == message.id, AuditEvent.action == "discussion.moderate.delete"
        )
    )
    assert event.actor_id == admin.id
    assert event.authorization_capability == Capability.discussion_moderate.value
    assert json.loads(event.detail)["reason"] == "Policy violation"


@pytest.mark.anyio
async def test_project_discussion_moderation_respects_lifecycle_and_lineage(async_db):
    owner = await _user(async_db, "project-discussion-moderator")
    author = await _user(async_db, "project-discussion-author")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=author.id,
            role=WorkspaceRole.reviewer,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db, owner, workspace_id, "Moderated Project", ProjectVisibility.managed
    )
    async_db.add(ProjectMember(workspace_id=workspace_id, project_id=project.id, user_id=author.id))
    await async_db.commit()
    message = await add_project_discussion_message(
        async_db, author, workspace_id, project.id, "Needs review"
    )
    with pytest.raises(ResourceUnavailable):
        await moderate_project_discussion_message(
            async_db, owner, workspace_id, "missing", message.id, "Policy"
        )
    with pytest.raises(ResourceUnavailable):
        await moderate_project_discussion_message(
            async_db, owner, workspace_id, project.id, "missing", "Policy"
        )
    project.state = ProjectState.archived
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await moderate_project_discussion_message(
            async_db, owner, workspace_id, project.id, message.id, "Policy"
        )
    project.state = ProjectState.active
    workspace = await async_db.get(Workspace, workspace_id)
    workspace.state = WorkspaceState.archived
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await moderate_project_discussion_message(
            async_db, owner, workspace_id, project.id, message.id, "Policy"
        )
    workspace.state = WorkspaceState.active
    await async_db.commit()
    await moderate_project_discussion_message(
        async_db, owner, workspace_id, project.id, message.id, "Policy violation"
    )
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.target_id == message.id,
            AuditEvent.action == "project.discussion.moderate.delete",
        )
    )
    assert event.project_id == project.id
    assert event.authorization_capability == Capability.discussion_moderate.value


@pytest.mark.anyio
async def test_private_annotation_author_can_manage_own_replies(async_db):
    author, viewer, item, _project, _revision, annotation, reply = await _shared_annotation_context(
        async_db, "private-annotation-replies"
    )
    workspace_id = fixture_workspace_id(author)
    annotation.scope = AnnotationScope.private
    annotation.project_item_id = None
    await async_db.commit()

    assert await editable_annotation_reply_ids(
        async_db, author, workspace_id, [reply], {annotation.id: annotation}
    ) == {reply.id}
    assert (
        await editable_annotation_reply_ids(
            async_db, viewer, workspace_id, [reply], {annotation.id: annotation}
        )
        == set()
    )

    created = await create_annotation_reply(
        async_db,
        author,
        workspace_id,
        item.id,
        annotation.id,
        AnnotationReplyCreate(id=uuid4(), body="Private reply"),
    )
    private_reply_id = created["id"]
    updated = await update_annotation_reply(
        async_db,
        author,
        workspace_id,
        item.id,
        annotation.id,
        private_reply_id,
        AnnotationReplyUpdate(version=created["version"], body="Updated private reply"),
    )
    await delete_annotation_reply(
        async_db,
        author,
        workspace_id,
        item.id,
        annotation.id,
        private_reply_id,
        updated["version"],
    )
    restored = await restore_annotation_reply(
        async_db,
        author,
        workspace_id,
        item.id,
        annotation.id,
        private_reply_id,
        updated["version"] + 1,
    )
    assert restored["body"] == "Updated private reply"


@pytest.mark.anyio
async def test_repeated_project_item_add_is_idempotent(async_db):
    owner = await _user(async_db, "project-item-owner")
    project = await create_project(async_db, owner, fixture_workspace_id(owner), "Working set")
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Assigned once",
        created_by=owner.id,
    )
    async_db.add(item)
    await async_db.commit()

    await add_item_to_project(async_db, owner, fixture_workspace_id(owner), project.id, item.id)
    await add_item_to_project(async_db, owner, fixture_workspace_id(owner), project.id, item.id)

    rows = (
        await async_db.scalars(
            select(ProjectItem).where(
                ProjectItem.workspace_id == fixture_workspace_id(owner),
                ProjectItem.project_id == project.id,
                ProjectItem.item_id == item.id,
            )
        )
    ).all()
    assert len(rows) == 1


@pytest.mark.anyio
async def test_project_item_rejects_cross_workspace_lineage(async_db):
    first = await _user(async_db, "first")
    second = await _user(async_db, "second")
    project = Project(
        workspace_id=fixture_workspace_id(first),
        name="First",
        created_by=first.id,
    )
    item = Item(
        workspace_id=fixture_workspace_id(second),
        title="Second",
        created_by=second.id,
    )
    async_db.add_all([project, item])
    await async_db.flush()
    async_db.add(
        ProjectItem(
            workspace_id=fixture_workspace_id(first),
            project_id=project.id,
            item_id=item.id,
            added_by=first.id,
        )
    )
    with pytest.raises(IntegrityError):
        await async_db.flush()


@pytest.mark.anyio
async def test_project_annotation_requires_revision_and_project_item_for_same_item(async_db):
    owner, _viewer, item, project, revision, annotation, _reply = await _shared_annotation_context(
        async_db, "annotation-item-constraint"
    )
    other = Item(workspace_id=item.workspace_id, title="Other Item", created_by=owner.id)
    async_db.add(other)
    await async_db.flush()
    other_project_item = ProjectItem(
        workspace_id=item.workspace_id,
        project_id=project.id,
        item_id=other.id,
        added_by=owner.id,
    )
    async_db.add(other_project_item)
    await async_db.commit()

    async def insert_mismatched_annotation():
        async with async_db.begin_nested():
            async_db.add(
                PdfAnnotation(
                    workspace_id=item.workspace_id,
                    file_revision_id=revision.id,
                    item_id=item.id,
                    page_index=0,
                    author_id=owner.id,
                    kind=AnnotationKind.note,
                    scope=AnnotationScope.project,
                    project_item_id=other_project_item.id,
                    payload={},
                )
            )
            await async_db.flush()

    with pytest.raises(IntegrityError):
        await insert_mismatched_annotation()

    async def update_mismatched_annotation():
        async with async_db.begin_nested():
            annotation.project_item_id = other_project_item.id
            await async_db.flush()

    with pytest.raises(IntegrityError):
        await update_mismatched_annotation()


@pytest.mark.anyio
async def test_detaching_project_item_cleans_annotation_and_reply_identities(async_db):
    owner, _viewer, item, project, _revision, annotation, reply = await _shared_annotation_context(
        async_db, "detach-annotation-identities"
    )
    await remove_item_from_project(async_db, owner, item.workspace_id, project.id, item.id)
    assert (
        await async_db.scalar(select(PdfAnnotation.id).where(PdfAnnotation.id == annotation.id))
        is None
    )
    assert (
        await async_db.scalar(
            select(PdfAnnotationReply.id).where(PdfAnnotationReply.id == reply.id)
        )
        is None
    )
    assert (
        await async_db.scalar(
            select(PdfAnnotationObject.id).where(PdfAnnotationObject.id == annotation.id)
        )
        is None
    )
    assert (
        await async_db.scalar(
            select(PdfAnnotationObject.id).where(PdfAnnotationObject.id == reply.id)
        )
        is None
    )


@pytest.mark.anyio
async def test_instance_admin_is_not_implicit_workspace_member(async_db):
    owner = await _user(async_db, "workspace-owner")
    admin = await _user(async_db, "instance-admin")
    admin.role = "administrator"
    await async_db.commit()

    with pytest.raises(WorkspaceMembershipRequired):
        await require_workspace_capability(
            async_db, admin, fixture_workspace_id(owner), Capability.workspace_read
        )


@pytest.mark.anyio
async def test_owner_must_transfer_before_suspension(async_db):
    owner = await _user(async_db, "transfer-owner")
    successor = await _user(async_db, "transfer-successor")
    successor_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=successor.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    async_db.add(successor_member)
    await async_db.commit()
    owner_member = await async_db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == fixture_workspace_id(owner),
            WorkspaceMember.user_id == owner.id,
            WorkspaceMember.terminated_at.is_(None),
        )
    )
    assert owner_member is not None

    with pytest.raises(PermissionDenied):
        await suspend_workspace_member(
            async_db, owner, fixture_workspace_id(owner), owner_member.id
        )

    await transfer_workspace_ownership(
        async_db, owner, fixture_workspace_id(owner), successor_member.id
    )
    await suspend_workspace_member(
        async_db, successor, fixture_workspace_id(owner), owner_member.id
    )
    with pytest.raises(WorkspaceMembershipRequired):
        await require_workspace_capability(
            async_db, owner, fixture_workspace_id(owner), Capability.workspace_read
        )


@pytest.mark.anyio
async def test_workspace_admin_cannot_appoint_an_admin(async_db):
    owner = await _user(async_db, "role-owner")
    admin = await _user(async_db, "role-admin")
    candidate = await _user(async_db, "role-candidate")
    admin_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=admin.id,
        role=WorkspaceRole.admin,
        invited_by=owner.id,
    )
    candidate_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=candidate.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    async_db.add_all([admin_member, candidate_member])
    await async_db.commit()

    with pytest.raises(PermissionDenied):
        await set_workspace_member_role(
            async_db,
            admin,
            fixture_workspace_id(owner),
            candidate_member.id,
            WorkspaceRole.admin,
        )


@pytest.mark.anyio
async def test_workspace_admin_cannot_suspend_another_admin(async_db):
    owner = await _user(async_db, "admin-governance-owner")
    actor = await _user(async_db, "admin-governance-actor")
    target = await _user(async_db, "admin-governance-target")
    actor_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=actor.id,
        role=WorkspaceRole.admin,
        invited_by=owner.id,
    )
    target_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=target.id,
        role=WorkspaceRole.admin,
        invited_by=owner.id,
    )
    async_db.add_all([actor_member, target_member])
    await async_db.commit()

    with pytest.raises(PermissionDenied):
        await suspend_workspace_member(
            async_db, actor, fixture_workspace_id(owner), target_member.id
        )


@pytest.mark.anyio
async def test_termination_clears_project_participation_without_affecting_access(async_db):
    owner = await _user(async_db, "project-member-owner")
    editor = await _user(async_db, "project-member-editor")
    editor_member = WorkspaceMember(
        workspace_id=fixture_workspace_id(owner),
        user_id=editor.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    async_db.add(editor_member)
    await async_db.commit()
    project = await create_project(
        async_db,
        owner,
        fixture_workspace_id(owner),
        "Project Member invariant",
        ProjectVisibility.managed,
    )
    await add_project_member(
        async_db, owner, fixture_workspace_id(owner), project.id, editor.username
    )
    workspace_id, project_id, owner_id, editor_id, editor_membership_id = (
        fixture_workspace_id(owner),
        project.id,
        owner.id,
        editor.id,
        editor_member.id,
    )

    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == owner_id,
            )
        )
        is None
    )
    await terminate_workspace_member(async_db, owner, workspace_id, editor_membership_id)

    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == editor_id,
            )
        )
        is None
    )


@pytest.mark.anyio
async def test_managed_project_participants_are_independent_of_workspace_governance(async_db):
    owner = await _user(async_db, "manager-owner")
    editor = await _user(async_db, "manager-editor")
    candidate = await _user(async_db, "manager-candidate")
    workspace_id = fixture_workspace_id(owner)
    async_db.add_all([
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        ),
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=candidate.id,
            role=WorkspaceRole.reviewer,
            invited_by=owner.id,
        ),
    ])
    await async_db.commit()

    project = await create_project(
        async_db, owner, workspace_id, "Governed direction", ProjectVisibility.managed
    )
    project_id = project.id
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(ProjectMember.project_id == project_id)
        )
        is None
    )
    await add_project_member(async_db, owner, workspace_id, project_id, editor.username)
    members = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
            )
        ).all()
    )
    assert members == {editor.id}
    context = await require_project_context(
        async_db, owner, workspace_id, project_id, Capability.workspace_read
    )
    assert context.project.id == project_id
    opened = await open_project_workspace(async_db, owner, workspace_id, project_id)
    assert {member.user.username for member in opened.members} == {editor.username}
    assert opened.is_member is False
    await set_project_state(async_db, owner, workspace_id, project_id, ProjectState.archived)
    await set_project_state(async_db, owner, workspace_id, project_id, ProjectState.active)
    await add_project_member(async_db, owner, workspace_id, project_id, candidate.username)
    await require_project_context(
        async_db, owner, workspace_id, project_id, Capability.workspace_read
    )


@pytest.mark.anyio
async def test_managed_project_can_have_no_participants(async_db):
    owner = await _user(async_db, "removable-owner")
    editor = await _user(async_db, "removable-editor")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(
        async_db, owner, workspace_id, "Explicit members", ProjectVisibility.managed
    )
    await add_project_member(async_db, owner, workspace_id, project.id, editor.username)
    await remove_project_member(async_db, owner, workspace_id, project.id, editor.id)
    members = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            )
        ).all()
    )
    assert members == set()
    context = await require_project_context(
        async_db, owner, workspace_id, project.id, Capability.workspace_read
    )
    assert context.project.id == project.id


@pytest.mark.anyio
async def test_workspace_project_has_implicit_participation_and_no_member_rows(async_db):
    owner = await _user(async_db, "workspace-scope-owner")
    editor = await _user(async_db, "workspace-scope-editor")
    workspace_id = fixture_workspace_id(owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=editor.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    await async_db.commit()
    project = await create_project(async_db, owner, workspace_id, "Workspace-visible")
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(ProjectMember.project_id == project.id)
        )
        is None
    )

    # Model a stale legacy association under a Workspace-visible Project.
    async_db.add(ProjectMember(workspace_id=workspace_id, project_id=project.id, user_id=editor.id))
    await async_db.commit()

    opened = await open_project_workspace(async_db, owner, workspace_id, project.id)
    assert opened.members == ()
    assert opened.is_member is True
    with pytest.raises(ProjectMemberConflict, match="managed Projects"):
        await add_project_member(async_db, owner, workspace_id, project.id, editor.username)
    with pytest.raises(ProjectMemberConflict, match="managed Projects"):
        await remove_project_member(async_db, owner, workspace_id, project.id, editor.id)
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(ProjectMember.project_id == project.id)
        )
        is not None
    )

    await update_project_settings(
        async_db,
        owner,
        workspace_id,
        project.id,
        name=project.name,
        description=project.description,
        visibility=ProjectVisibility.open,
    )
    members = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            )
        ).all()
    )
    assert members == {owner.id}

    await join_project(async_db, editor, workspace_id, project.id)
    await leave_project(async_db, editor, workspace_id, project.id)
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == editor.id,
            )
        )
        is None
    )
    await join_project(async_db, editor, workspace_id, project.id)
    await update_project_settings(
        async_db,
        owner,
        workspace_id,
        project.id,
        name=project.name,
        description=project.description,
        visibility=ProjectVisibility.managed,
    )
    members = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            )
        ).all()
    )
    assert members == {owner.id, editor.id}
    await update_project_settings(
        async_db,
        owner,
        workspace_id,
        project.id,
        name=project.name,
        description=project.description,
        visibility=ProjectVisibility.workspace,
    )
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(ProjectMember.project_id == project.id)
        )
        is None
    )


@pytest.mark.anyio
async def test_workspace_ownership_transfer_preserves_project_participation(async_db):
    owner = await _user(async_db, "visibility-manager-owner")
    editor = await _user(async_db, "visibility-manager-editor")
    successor = await _user(async_db, "visibility-manager-successor")
    workspace_id = fixture_workspace_id(owner)
    editor_membership = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=editor.id,
        role=WorkspaceRole.editor,
        invited_by=owner.id,
    )
    successor_membership = WorkspaceMember(
        workspace_id=workspace_id,
        user_id=successor.id,
        role=WorkspaceRole.viewer,
        invited_by=owner.id,
    )
    async_db.add_all([editor_membership, successor_membership])
    await async_db.commit()

    project = await create_project(async_db, editor, workspace_id, "Open direction")
    await update_project_settings(
        async_db,
        editor,
        workspace_id,
        project.id,
        name=project.name,
        description=project.description,
        visibility=ProjectVisibility.open,
    )
    members = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            )
        ).all()
    )
    assert members == {editor.id}

    await transfer_workspace_ownership(async_db, owner, workspace_id, successor_membership.id)
    members_after = set(
        (
            await async_db.scalars(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
            )
        ).all()
    )
    assert members_after == members
    await terminate_workspace_member(
        async_db,
        successor,
        workspace_id,
        (
            await async_db.scalar(
                select(WorkspaceMember.id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == owner.id,
                    WorkspaceMember.terminated_at.is_(None),
                )
            )
        ),
    )
    # Workspace ownership remains authoritative. The open Project remains visible to all members.
    await set_project_state(async_db, successor, workspace_id, project.id, ProjectState.archived)
    await set_project_state(async_db, successor, workspace_id, project.id, ProjectState.active)
    context = await require_project_context(
        async_db, successor, workspace_id, project.id, Capability.workspace_read
    )
    assert context.project.id == project.id
    await join_project(async_db, successor, workspace_id, project.id)
    await set_project_state(async_db, successor, workspace_id, project.id, ProjectState.archived)


@pytest.mark.anyio
async def test_project_annotation_bundle_hides_managed_content_from_nonmembers(async_db):
    owner, former_member, item, project, revision, _, _ = await _shared_annotation_context(
        async_db, "bundle-annotation-scope"
    )
    workspace_id = fixture_workspace_id(owner)
    reviewer_membership = await async_db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == former_member.id,
        )
    )
    assert reviewer_membership is not None
    reviewer_membership.role = WorkspaceRole.reviewer
    await update_project_settings(
        async_db,
        owner,
        workspace_id,
        project.id,
        name=project.name,
        description=project.description,
        visibility=ProjectVisibility.managed,
    )
    project_item = await async_db.scalar(
        select(ProjectItem).where(ProjectItem.project_id == project.id)
    )
    assert project_item is not None
    visible = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=former_member.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        payload={},
    )
    hidden = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=former_member.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        hidden_at=datetime.now(UTC),
        payload={},
    )
    archived = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=former_member.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        archived_at=datetime.now(UTC),
        payload={},
    )
    private = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=former_member.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
        payload={},
    )
    async_db.add_all([visible, hidden, archived, private])
    await async_db.commit()
    assert {row.id for row in await _own_annotations(async_db, former_member, revision)} == {
        private.id,
    }
    assert (
        await async_db.scalar(
            select(ProjectMember.id).where(
                ProjectMember.project_id == project.id,
                ProjectMember.user_id == former_member.id,
            )
        )
        is None
    )
    project.state = ProjectState.deleted
    await async_db.commit()
    assert [row.id for row in await _own_annotations(async_db, former_member, revision)] == [
        private.id
    ]


@pytest.mark.anyio
async def test_item_organize_omits_deleted_projects(async_db):
    owner = await _user(async_db, "organize-deleted-owner")
    workspace_id = fixture_workspace_id(owner)
    item = Item(workspace_id=workspace_id, title="Organize target", created_by=owner.id)
    async_db.add(item)
    await async_db.commit()
    project = await create_project(async_db, owner, workspace_id, "Deleted project")
    await add_item_to_project(async_db, owner, workspace_id, project.id, item.id)
    before = await open_item_section(async_db, owner, workspace_id, item.id, ItemSection.organize)
    assert project.id in {option.project.id for option in before.projects}

    await delete_project(async_db, owner, workspace_id, project.id, project.name)
    after = await open_item_section(async_db, owner, workspace_id, item.id, ItemSection.organize)
    assert project.id not in {option.project.id for option in after.projects}
    assert project.id not in after.assigned_project_ids


@pytest.mark.anyio
async def test_governance_suspension_is_read_only(async_db):
    owner = await _user(async_db, "suspended-owner")
    admin = await _user(async_db, "suspending-instance-admin")
    admin.role = "administrator"
    await async_db.commit()
    await suspend_workspace_governance(async_db, admin, fixture_workspace_id(owner))

    await require_workspace_capability(
        async_db, owner, fixture_workspace_id(owner), Capability.workspace_read
    )
    with pytest.raises(WorkspaceLifecycleError):
        await require_workspace_capability(
            async_db, owner, fixture_workspace_id(owner), Capability.items_create
        )


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["suspend", "recover", "break_glass"])
async def test_workspace_governance_rechecks_instance_admin_authority(
    async_db, async_session_factory, operation
):
    owner = await _user(async_db, f"stale-governance-{operation}-owner")
    admin = await _user(async_db, f"stale-governance-{operation}-admin")
    admin.role = "administrator"
    await async_db.commit()
    workspace_id = fixture_workspace_id(owner)

    async with async_session_factory() as authority_db:
        current_admin = await authority_db.get(User, admin.id)
        assert current_admin is not None
        current_admin.role = "member"
        await authority_db.commit()

    if operation == "suspend":
        governance_call = suspend_workspace_governance(async_db, admin, workspace_id)
    elif operation == "recover":
        governance_call = recover_workspace_governance(async_db, admin, workspace_id)
    else:
        governance_call = read_workspace_items_break_glass(
            async_db, admin, workspace_id, "Investigate stale authority"
        )
    with pytest.raises(ResourceNotFound, match="Workspace not found"):
        await governance_call

    action = {
        "suspend": "admin.workspace.suspend",
        "recover": "admin.workspace.recover",
        "break_glass": "admin.workspace.break_glass.read",
    }[operation]
    assert await async_db.scalar(select(AuditEvent.id).where(AuditEvent.action == action)) is None


@pytest.mark.anyio
async def test_workspace_reindex_payload_carries_actor_and_workspace(
    async_db, fake_durable_operations
):
    owner = await _user(async_db, "reindex-owner")

    workflow_id = await dispatch_workspace_reindex(async_db, owner, fixture_workspace_id(owner))

    enqueue = fake_durable_operations.enqueues[-1]
    assert enqueue["workflow_name"] == "operations.reindex_workspace"
    assert enqueue["args"] == (workflow_id, owner.id, fixture_workspace_id(owner))
    assert enqueue["attributes"] == {
        "capability": "operations",
        "operation": "reindex",
        "actor_id": owner.id,
        "workspace_id": fixture_workspace_id(owner),
    }


@pytest.mark.anyio
async def test_break_glass_is_one_shot_read_only_and_audited(async_db):
    owner = await _user(async_db, "break-glass-owner")
    admin = await _user(async_db, "break-glass-admin")
    admin.role = "administrator"
    async_db.add(
        Item(
            workspace_id=fixture_workspace_id(owner),
            title="Sensitive title",
            created_by=owner.id,
        )
    )
    await async_db.commit()

    items = await read_workspace_items_break_glass(
        async_db,
        admin,
        fixture_workspace_id(owner),
        "Investigate customer-reported data loss",
    )
    assert [item.title for item in items] == ["Sensitive title"]
    with pytest.raises(WorkspaceMembershipRequired):
        await require_workspace_capability(
            async_db, admin, fixture_workspace_id(owner), Capability.workspace_read
        )
    event = await async_db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "admin.workspace.break_glass.read",
            AuditEvent.workspace_id == fixture_workspace_id(owner),
        )
    )
    assert event is not None
    assert event.source == "break_glass"


@pytest.mark.anyio
async def test_annotation_moderation_preserves_authored_content_and_hides_shared_scope(async_db):
    owner = await _user(async_db, "moderation-owner")
    author = await _user(async_db, "moderation-author")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(owner),
            user_id=author.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
    )
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Moderated item",
        created_by=author.id,
    )
    project = Project(
        workspace_id=fixture_workspace_id(owner),
        name="Moderated project",
        created_by=author.id,
    )
    async_db.add_all([item, project])
    await async_db.flush()
    project_item = ProjectItem(
        workspace_id=fixture_workspace_id(owner),
        project_id=project.id,
        item_id=item.id,
        added_by=author.id,
    )
    revision = FileRevision(
        workspace_id=fixture_workspace_id(owner),
        item_id=item.id,
        object_key="objects/moderation.pdf",
        size=1,
        original_name="moderation.pdf",
        created_by=author.id,
    )
    async_db.add_all([project_item, revision])
    await async_db.flush()
    annotation = PdfAnnotation(
        workspace_id=fixture_workspace_id(owner),
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        body="Authored body",
        payload={"type": "note", "rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
    )
    async_db.add(annotation)
    await async_db.commit()

    moderated = await moderate_document_annotation(
        async_db,
        owner,
        fixture_workspace_id(owner),
        item.id,
        annotation.id,
        "hide",
        1,
    )

    assert moderated["body"] == "Authored body"
    assert moderated["moderated_by"] == owner.id
    assert moderated["hidden_at"] is not None
    assert (
        await list_document_annotations(
            async_db,
            author,
            fixture_workspace_id(owner),
            item.id,
            revision.id,
            project.id,
        )
        == []
    )
    assert (
        len(
            await list_document_annotations(
                async_db,
                owner,
                fixture_workspace_id(owner),
                item.id,
                revision.id,
                project.id,
            )
        )
        == 1
    )
    author_view = await open_item_section(
        async_db, author, fixture_workspace_id(owner), item.id, ItemSection.annotations
    )
    owner_view = await open_item_section(
        async_db, owner, fixture_workspace_id(owner), item.id, ItemSection.annotations
    )
    assert not author_view.annotations
    assert [entry.annotation.id for entry in owner_view.annotations] == [annotation.id]


@pytest.mark.anyio
async def test_annotation_reads_return_non_editable_flags_for_viewers_and_archived_workspace(
    async_db,
):
    author, viewer, item, project, revision, annotation, reply = await _shared_annotation_context(
        async_db, "read-only-annotations"
    )
    workspace_id = fixture_workspace_id(author)

    visible = await list_document_annotations(
        async_db, viewer, workspace_id, item.id, revision.id, project.id
    )
    assert [entry["id"] for entry in visible] == [annotation.id]
    assert visible[0]["editable"] is False
    assert visible[0]["replies"][0]["id"] == reply.id
    assert visible[0]["replies"][0]["editable"] is False

    await archive_workspace(async_db, author, workspace_id)
    archived = await list_document_annotations(
        async_db, author, workspace_id, item.id, revision.id, project.id
    )
    assert [entry["id"] for entry in archived] == [annotation.id]
    assert archived[0]["editable"] is False
    assert archived[0]["replies"][0]["editable"] is False
    review = await review_item_annotations(
        async_db, author, workspace_id, item.id, page=1, per_page=20
    )
    assert review.total == 1
    assert review.annotations[0]["editable"] is False


@pytest.mark.anyio
async def test_archived_project_blocks_mutating_existing_annotations(async_db):
    author, _, item, project, revision, annotation, reply = await _shared_annotation_context(
        async_db, "archived-project-annotation"
    )
    workspace_id = fixture_workspace_id(author)
    await set_project_state(async_db, author, workspace_id, project.id, ProjectState.archived)

    visible = await list_document_annotations(
        async_db, author, workspace_id, item.id, revision.id, project.id
    )
    assert visible[0]["editable"] is False
    with pytest.raises(WorkspaceLifecycleError):
        await delete_document_annotation(
            async_db, author, workspace_id, item.id, annotation.id, annotation.version
        )
    with pytest.raises(WorkspaceLifecycleError):
        await update_document_annotation(
            async_db,
            author,
            workspace_id,
            item.id,
            annotation.id,
            AnnotationUpdate.model_validate({
                "version": annotation.version,
                "page_index": 0,
                "kind": "note",
                "scope": "private",
                "body": "Moved to private",
                "payload": annotation.payload,
            }),
        )
    with pytest.raises(WorkspaceLifecycleError):
        await create_annotation_reply(
            async_db,
            author,
            workspace_id,
            item.id,
            annotation.id,
            AnnotationReplyCreate(id=uuid4(), body="After archive"),
        )
    with pytest.raises(WorkspaceLifecycleError):
        await update_annotation_reply(
            async_db,
            author,
            workspace_id,
            item.id,
            annotation.id,
            reply.id,
            AnnotationReplyUpdate(version=reply.version, body="Edited after archive"),
        )
    with pytest.raises(WorkspaceLifecycleError):
        await delete_annotation_reply(
            async_db, author, workspace_id, item.id, annotation.id, reply.id, reply.version
        )
    annotation.deleted_at = datetime.now(UTC)
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await restore_document_annotation(
            async_db, author, workspace_id, item.id, annotation.id, annotation.version
        )


@pytest.mark.anyio
async def test_project_restore_requires_writable_workspace(async_db):
    author, _, _, project, _, _, _ = await _shared_annotation_context(
        async_db, "project-restore-lifecycle"
    )
    workspace_id = fixture_workspace_id(author)
    await set_project_state(async_db, author, workspace_id, project.id, ProjectState.archived)
    workspace = await async_db.get(Workspace, workspace_id)
    assert workspace is not None
    workspace.state = WorkspaceState.archived
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await set_project_state(async_db, author, workspace_id, project.id, ProjectState.active)

    workspace.state = WorkspaceState.active
    workspace.governance_suspended_at = datetime.now(UTC)
    workspace.governance_suspended_by = author.id
    await async_db.commit()
    with pytest.raises(WorkspaceLifecycleError):
        await set_project_state(async_db, author, workspace_id, project.id, ProjectState.active)
    assert project.state is ProjectState.archived


@pytest.mark.anyio
async def test_deleted_project_annotations_are_excluded_from_item_review(async_db):
    author, _, item, project, _, annotation, _ = await _shared_annotation_context(
        async_db, "deleted-project-review"
    )
    workspace_id = fixture_workspace_id(author)
    before = await review_item_annotations(
        async_db, author, workspace_id, item.id, page=1, per_page=20
    )
    assert [entry["id"] for entry in before.annotations] == [annotation.id]

    project.state = ProjectState.deleted
    await async_db.commit()
    after = await review_item_annotations(
        async_db, author, workspace_id, item.id, page=1, per_page=20
    )
    assert after.total == 0
    assert after.annotations == ()


@pytest.mark.anyio
async def test_committed_object_cleanup_survives_workspace_archive_and_role_change(
    async_db, fake_durable_operations
):
    owner = await _user(async_db, "cleanup-after-access-change")
    workspace_id = fixture_workspace_id(owner)
    item = Item(workspace_id=workspace_id, title="Cleanup item", created_by=owner.id)
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.BINARY, b"obsolete attachment", max_bytes=1024
    )
    async_db.add(item)
    await async_db.flush()
    attachment = Attachment(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key=stored.key,
        size=stored.size,
        original_name="obsolete.bin",
        created_by=owner.id,
    )
    async_db.add(attachment)
    await async_db.commit()

    await delete_attachment(async_db, owner, workspace_id, item.id, attachment.id)
    await async_db.commit()
    cleanup = fake_durable_operations.enqueues[-1]
    assert cleanup["workflow_name"] == "documents.cleanup_objects"
    await archive_workspace(async_db, owner, workspace_id)
    membership = await async_db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == owner.id,
        )
    )
    assert membership is not None
    membership.role = WorkspaceRole.viewer
    await async_db.commit()

    deleted = await delete_unreferenced_objects_step(
        owner.id, workspace_id, [stored.key], cleanup["workflow_id"]
    )
    assert deleted == [stored.key]
    assert not await get_object_store().exists(stored.key)


@pytest.mark.anyio
async def test_annotation_export_status_and_file_are_requester_only(
    async_db, fake_durable_operations
):
    requester = await _user(async_db, "export-requester")
    peer = await _user(async_db, "export-peer")
    workspace_id = fixture_workspace_id(requester)
    async_db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=peer.id,
            role=WorkspaceRole.viewer,
            invited_by=requester.id,
        )
    )
    await async_db.commit()
    workflow_id = f"annotation-export:{uuid4()}"
    fake_durable_operations.workflows[workflow_id] = WorkflowSummary(
        id=workflow_id,
        name=ANNOTATION_EXPORT_WORKFLOW,
        state="succeeded",
        raw_status="SUCCESS",
        queue_name=None,
        executor_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        output={"revision_id": "private-revision", "object_key": "private.pdf"},
        attributes={"actor_id": requester.id, "workspace_id": workspace_id},
    )

    assert (await get_export_status(async_db, requester, workspace_id, workflow_id))[
        "state"
    ] == "succeeded"
    with pytest.raises(ResourceNotFound):
        await get_export_status(async_db, peer, workspace_id, workflow_id)
    with pytest.raises(ResourceNotFound):
        await get_export_file(async_db, peer, workspace_id, workflow_id)


@pytest.mark.anyio
async def test_project_annotation_export_file_rejects_replaced_assignment(
    async_db, fake_durable_operations
):
    requester = await _user(async_db, "project-export-requester")
    workspace_id = fixture_workspace_id(requester)
    item = Item(workspace_id=workspace_id, title="Project export", created_by=requester.id)
    project = Project(workspace_id=workspace_id, name="Project export", created_by=requester.id)
    async_db.add_all([item, project])
    await async_db.flush()
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-project-export", max_bytes=1024
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key="objects/source.pdf",
        size=1,
        original_name="source.pdf",
        created_by=requester.id,
    )
    assignment = ProjectItem(
        workspace_id=workspace_id,
        project_id=project.id,
        item_id=item.id,
        added_by=requester.id,
    )
    async_db.add_all([revision, assignment])
    await async_db.commit()
    original_assignment_id = assignment.id

    await async_db.delete(assignment)
    await async_db.commit()
    async_db.add(
        ProjectItem(
            workspace_id=workspace_id,
            project_id=project.id,
            item_id=item.id,
            added_by=requester.id,
        )
    )
    await async_db.commit()

    workflow_id = f"annotation-export:{uuid4()}"
    fake_durable_operations.workflows[workflow_id] = WorkflowSummary(
        id=workflow_id,
        name=ANNOTATION_EXPORT_WORKFLOW,
        state="succeeded",
        raw_status="SUCCESS",
        queue_name=None,
        executor_id=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        output={
            "revision_id": revision.id,
            "object_key": stored.key,
            "project_id": project.id,
            "project_item_id": original_assignment_id,
        },
        attributes={"actor_id": requester.id, "workspace_id": workspace_id},
    )

    with pytest.raises(ResourceUnavailable, match="project item not found"):
        await get_export_file(async_db, requester, workspace_id, workflow_id)


@pytest.mark.anyio
async def test_cross_workspace_copy_creates_detached_item_and_file(async_db, monkeypatch):
    actor = await _user(async_db, "copy-actor")
    target_owner = await _user(async_db, "copy-target-owner")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(target_owner),
            user_id=actor.id,
            role=WorkspaceRole.editor,
            invited_by=target_owner.id,
        )
    )
    source = Item(
        workspace_id=fixture_workspace_id(actor),
        title="Detached source",
        abstract="metadata copy",
        created_by=actor.id,
    )
    async_db.add(source)
    await async_db.flush()
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-independent-copy", max_bytes=1024
    )
    source_revision = FileRevision(
        workspace_id=fixture_workspace_id(actor),
        item_id=source.id,
        object_key=stored.key,
        size=stored.size,
        original_name="source.pdf",
        full_text="Unique copied PDF search phrase",
        processing_state="ready",
        created_by=actor.id,
    )
    async_db.add(source_revision)
    await async_db.commit()

    store = get_object_store()

    class TransactionCheckingStore:
        async def get(self, *args, **kwargs):
            assert not async_db.in_transaction()
            return await store.get(*args, **kwargs)

        async def put_object(self, *args, **kwargs):
            assert not async_db.in_transaction()
            return await store.put_object(*args, **kwargs)

        async def delete(self, *args, **kwargs):
            return await store.delete(*args, **kwargs)

    monkeypatch.setattr(
        "quirebase.library.cross_workspace.get_object_store",
        TransactionCheckingStore,
    )

    copied = await copy_item_to_workspace(
        async_db,
        actor,
        fixture_workspace_id(actor),
        fixture_workspace_id(target_owner),
        source.id,
    )
    copied_revision = await async_db.scalar(
        select(FileRevision).where(FileRevision.item_id == copied.id)
    )

    assert copied.id != source.id
    assert copied.workspace_id == fixture_workspace_id(target_owner)
    assert copied.title == source.title
    assert copied_revision is not None
    assert copied_revision.object_key != source_revision.object_key
    assert await get_object_store().exists(source_revision.object_key)
    assert await get_object_store().exists(copied_revision.object_key)
    assert await search_index(async_db).search(async_db, "copied PDF search") == [copied.id]


@pytest.mark.anyio
async def test_cross_workspace_copy_preserves_objects_after_ambiguous_commit(async_db, monkeypatch):
    actor = await _user(async_db, "ambiguous-copy-actor")
    target_owner = await _user(async_db, "ambiguous-copy-target-owner")
    target_workspace_id = fixture_workspace_id(target_owner)
    async_db.add(
        WorkspaceMember(
            workspace_id=target_workspace_id,
            user_id=actor.id,
            role=WorkspaceRole.editor,
            invited_by=target_owner.id,
        )
    )
    source = Item(
        workspace_id=fixture_workspace_id(actor),
        title="Ambiguous commit source",
        created_by=actor.id,
    )
    async_db.add(source)
    await async_db.flush()
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-ambiguous-copy", max_bytes=1024
    )
    async_db.add(
        FileRevision(
            workspace_id=source.workspace_id,
            item_id=source.id,
            object_key=stored.key,
            size=stored.size,
            original_name="ambiguous.pdf",
            processing_state="ready",
            created_by=actor.id,
        )
    )
    await async_db.commit()

    real_commit = async_db.commit
    commit_count = 0

    async def commit_then_lose_acknowledgement():
        nonlocal commit_count
        await real_commit()
        commit_count += 1
        if commit_count == 2:
            raise ConnectionError("commit acknowledgement lost")

    monkeypatch.setattr(async_db, "commit", commit_then_lose_acknowledgement)

    with pytest.raises(ConnectionError, match="acknowledgement lost"):
        await copy_item_to_workspace(
            async_db,
            actor,
            source.workspace_id,
            target_workspace_id,
            source.id,
        )

    copied = await async_db.scalar(
        select(Item).where(
            Item.workspace_id == target_workspace_id,
            Item.title == "Ambiguous commit source",
        )
    )
    assert copied is not None
    copied_revision = await async_db.scalar(
        select(FileRevision).where(FileRevision.item_id == copied.id)
    )
    assert copied_revision is not None
    assert await get_object_store().exists(copied_revision.object_key)


@pytest.mark.anyio
async def test_cross_workspace_copy_rejects_pending_file_revision(async_db):
    actor = await _user(async_db, "pending-copy-actor")
    target_owner = await _user(async_db, "pending-copy-target-owner")
    async_db.add(
        WorkspaceMember(
            workspace_id=fixture_workspace_id(target_owner),
            user_id=actor.id,
            role=WorkspaceRole.editor,
        )
    )
    source = Item(
        workspace_id=fixture_workspace_id(actor),
        title="Pending source",
        created_by=actor.id,
    )
    async_db.add(source)
    await async_db.flush()
    async_db.add(
        FileRevision(
            workspace_id=source.workspace_id,
            item_id=source.id,
            object_key="objects/pending-copy.pdf",
            size=1,
            original_name="pending.pdf",
            processing_state="pending",
            created_by=actor.id,
        )
    )
    await async_db.commit()

    with pytest.raises(ValidationFailure, match="must be ready"):
        await copy_item_to_workspace(
            async_db, actor, source.workspace_id, fixture_workspace_id(target_owner), source.id
        )
    assert (
        await async_db.scalar(
            select(Item.id).where(Item.workspace_id == fixture_workspace_id(target_owner))
        )
        is None
    )
