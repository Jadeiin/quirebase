from datetime import UTC, datetime
from uuid import uuid4

import pymupdf
import pytest
from sqlalchemy import event, select
from test_http import authenticated_async_client
from workspace_helpers import provision_initial_workspace

from quirebase.access import (
    ResourceAction,
    WorkspaceContext,
    authorization,
    effective_resource_actions,
    item_decisions,
    project_decisions,
    project_participation_change_allowed,
    require_action,
    require_project_context,
    require_project_participation_change,
    resolve_workspace_context,
    workspace_member_roles,
)
from quirebase.accounts import create_api_token
from quirebase.core.errors import PermissionDenied, WorkspaceLifecycleError
from quirebase.documents import create_attachment, store_pdf_revision
from quirebase.documents.workflows import (
    commit_uploaded_attachment,
    commit_uploaded_revision,
    inspect_uploaded_pdf,
)
from quirebase.models import (
    Attachment,
    FileRevision,
    Project,
    ProjectParticipation,
    ProjectState,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.operations import dispatch_workspace_reindex
from quirebase.projects import create_project
from quirebase.workspaces import set_workspace_member_role


@pytest.fixture
def policy_bundle(tmp_path, monkeypatch):
    """Vary real Casbin grants; a role matrix alone cannot catch incidental gating."""
    original = authorization._POLICY_PATH.read_text()
    policy = tmp_path / "policy.csv"

    def clear():
        for cached in (
            authorization._enforcer,
            authorization._validate_policy_bundle,
            authorization._enforce_canonical,
            effective_resource_actions,
        ):
            cached.cache_clear()

    def configure(*changes):
        content = original
        for action, current, target in changes:
            prefix = f"p, workspace:{current}, {action.resource}, {action.action},"
            assert prefix in content
            content = content.replace(
                prefix, f"p, workspace:{target}, {action.resource}, {action.action},"
            )
        policy.write_text(content)
        monkeypatch.setattr(authorization, "_POLICY_PATH", policy)
        clear()
        authorization.initialize_authorization()

    yield configure
    clear()


def _context(role, lifecycle="active"):
    actor = User(id=str(uuid4()), username="projection", password_hash="unused")
    workspace = Workspace(
        id=str(uuid4()),
        name="Projection",
        created_by=actor.id,
        state=WorkspaceState.archived if lifecycle == "archived" else WorkspaceState.active,
        governance_suspended_at=datetime.now(UTC) if lifecycle == "suspended" else None,
    )
    member = WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=role)
    return WorkspaceContext(actor, workspace, member, role)


ITEM_SURFACE_ACTIONS = (
    ResourceAction.item_update,
    ResourceAction.item_delete,
    ResourceAction.file_manage,
    ResourceAction.file_delete,
    ResourceAction.tag_use,
    ResourceAction.tag_create,
    ResourceAction.project_item_manage,
    ResourceAction.workspace_export,
)


@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "suspended"])
def test_item_surface_projects_each_enforceable_action(role, lifecycle):
    context = _context(role, lifecycle)
    projected = set(item_decisions(context).allowed)
    for action in ITEM_SURFACE_ACTIONS:
        try:
            require_action(context, action)
        except (PermissionDenied, WorkspaceLifecycleError):
            assert action not in projected
        else:
            assert action in projected


@pytest.mark.parametrize("action", ITEM_SURFACE_ACTIONS)
def test_item_projection_does_not_infer_independent_grants(policy_bundle, action):
    # Leave exactly one surface capability granted to an editor.
    changes = []
    for candidate in ITEM_SURFACE_ACTIONS:
        current = (
            "viewer"
            if candidate is ResourceAction.workspace_export
            else ("admin" if candidate is ResourceAction.item_delete else "editor")
        )
        target = "editor" if candidate is action else "owner"
        if target != current:
            changes.append((candidate, current, target))
    policy_bundle(*changes)
    context = _context(WorkspaceRole.editor)
    assert item_decisions(context).allowed == (action,)
    require_action(context, action)


def test_restore_projection_requires_archived_project_even_without_archive_grant(policy_bundle):
    policy_bundle((ResourceAction.project_archive, "editor", "owner"))
    context = _context(WorkspaceRole.editor)
    project = Project(
        workspace_id=context.workspace_id,
        name="Independent restore",
        created_by=context.actor_id,
        participation=ProjectParticipation.workspace,
        state=ProjectState.active,
    )
    require_action(context, ResourceAction.project_restore)
    active = project_decisions(context, project, is_participating=True)
    assert ResourceAction.project_archive not in active.allowed
    assert ResourceAction.project_restore not in active.allowed
    project.state = ProjectState.archived
    assert (
        ResourceAction.project_restore
        in project_decisions(context, project, is_participating=True).allowed
    )


@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "suspended"])
@pytest.mark.parametrize("current", ProjectParticipation)
@pytest.mark.parametrize("target", ProjectParticipation)
def test_participation_choices_match_enforcement_for_every_transition(
    role, lifecycle, current, target
):
    context = _context(role, lifecycle)
    governance_transitions = {
        ("workspace", "managed"),
        ("open", "managed"),
        ("managed", "workspace"),
        ("managed", "open"),
    }
    expected = lifecycle == "active" and role in {
        WorkspaceRole.owner,
        WorkspaceRole.admin,
        WorkspaceRole.editor,
    }
    if (current.value, target.value) in governance_transitions:
        expected = expected and role in {WorkspaceRole.owner, WorkspaceRole.admin}
    assert project_participation_change_allowed(context, current, target) is expected
    if expected:
        require_project_participation_change(context, current, target)
    else:
        with pytest.raises((PermissionDenied, WorkspaceLifecycleError)):
            require_project_participation_change(context, current, target)


@pytest.mark.anyio
async def test_child_mutations_and_upload_finalizers_do_not_require_metadata_edit(
    async_db, async_session_factory, tmp_path, monkeypatch, policy_bundle
):
    policy_bundle((ResourceAction.item_update, "editor", "admin"))
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    actor = User(username="child-editor", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace_id, item_id, actor_id = item.workspace_id, item.id, actor.id
    async_db.add(
        WorkspaceMember(workspace_id=workspace_id, user_id=actor_id, role=WorkspaceRole.editor)
    )
    tag = Tag(workspace_id=workspace_id, name="Existing", created_by=item.created_by)
    project = Project(workspace_id=workspace_id, name="Assignment", created_by=item.created_by)
    async_db.add_all([tag, project])
    await async_db.commit()
    grant = await create_api_token(async_db, actor, "Independent capabilities", expires_in_days=1)
    client.headers["Authorization"] = f"Bearer {grant.raw_token}"
    base = f"/api/v1/workspaces/{workspace_id}"
    try:
        overview = await client.get(f"{base}/items/{item_id}/overview")
        organize = await client.get(f"{base}/items/{item_id}/organize")
        assert overview.status_code == organize.status_code == 200
        actions = set(overview.json()["authorization"]["allowed"])
        assert "item.update" not in actions and "item.delete" not in actions
        assert {
            "file.manage",
            "file.delete",
            "tag.use",
            "tag.create",
            "project_item.manage",
        } <= actions
        assert organize.json()["authorization"] == overview.json()["authorization"]
        assigned = await client.put(
            f"{base}/items/{item_id}/tags",
            json={"add_tag_ids": [tag.id], "remove_tag_ids": [], "new_names": ["New"]},
        )
        assert assigned.status_code == 200
        assert (await client.delete(f"{base}/items/{item_id}/tags/{tag.id}")).status_code == 200
        assert (
            await client.put(f"{base}/projects/{project.id}/items/{item_id}")
        ).status_code == 200
        assert (
            await client.delete(f"{base}/projects/{project.id}/items/{item_id}")
        ).status_code == 200

        with pymupdf.open() as document:
            document.new_page()
            pdf = document.tobytes()
        upload = await store_pdf_revision(
            async_db, actor, workspace_id, item_id, pdf, "independent.pdf"
        )
        inspected = await inspect_uploaded_pdf(
            str(upload.object_id),
            str(upload.object_id),
            str(uuid4()),
            {"status": "complete", "key": upload.object_key, "size": len(pdf)},
        )
        result = await commit_uploaded_revision(
            actor_id, workspace_id, item_id, "independent.pdf", inspected
        )
        assert await async_db.get(FileRevision, result["revision_id"]) is not None
        actor = await async_db.get(User, actor_id)
        attachment = await create_attachment(
            async_db, actor, workspace_id, item_id, b"data", "independent.txt"
        )
        result = await commit_uploaded_attachment(
            actor_id,
            workspace_id,
            item_id,
            str(attachment.object_id),
            "independent.txt",
            "text/plain",
            None,
            {"object_key": attachment.object_key, "size": 4},
        )
        assert await async_db.get(Attachment, result["attachment_id"]) is not None
        assert (
            await client.delete(f"{base}/items/{item_id}/attachments/{result['attachment_id']}")
        ).status_code == 200
        assert (
            await client.request(
                "DELETE", f"{base}/items/{item_id}", json={"confirmation": "delete"}
            )
        ).status_code == 403
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("role", [WorkspaceRole.owner, WorkspaceRole.admin])
@pytest.mark.parametrize(
    ("target_role", "state"),
    [
        (role, state)
        for role in WorkspaceRole
        for state in WorkspaceMemberState
        if role is not WorkspaceRole.owner or state is WorkspaceMemberState.active
    ],
)
async def test_concrete_member_roles_match_actual_transitions(async_db, role, target_role, state):
    owner = User(username="roles-owner", password_hash="unused")
    actor = (
        owner
        if role is WorkspaceRole.owner
        else User(username="roles-admin", password_hash="unused")
    )
    target = User(username="roles-target", password_hash="unused")
    async_db.add_all([owner, target] if actor is owner else [owner, actor, target])
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    if actor is not owner:
        async_db.add(WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=role))
    member = (
        (
            await async_db.scalar(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)
            )
        )
        if target_role is WorkspaceRole.owner
        else WorkspaceMember(
            workspace_id=workspace.id, user_id=target.id, role=target_role, state=state
        )
    )
    if target_role is not WorkspaceRole.owner:
        async_db.add(member)
    await async_db.commit()
    context = await resolve_workspace_context(async_db, actor, workspace.id)
    choices = workspace_member_roles(context, member)
    expected = (
        []
        if target_role is WorkspaceRole.owner
        or (role is WorkspaceRole.admin and target_role is WorkspaceRole.admin)
        else (
            ["admin", "editor", "reviewer", "viewer"]
            if role is WorkspaceRole.owner
            else ["editor", "reviewer", "viewer"]
        )
    )
    assert list(choices) == expected
    initial_role = member.role
    for requested in choices:
        # Restore source facts so every option represents the displayed transition.
        member.role = initial_role
        await async_db.commit()
        updated = await set_workspace_member_role(
            async_db, actor, workspace.id, member.id, requested.value
        )
        assert updated.role.value == requested.value


@pytest.mark.anyio
@pytest.mark.parametrize("maintenance_allowed", [False, True])
async def test_maintenance_authority_is_independent_of_workspace_rename(
    async_db, policy_bundle, maintenance_allowed
):
    removed = (
        ResourceAction.workspace_update
        if maintenance_allowed
        else ResourceAction.workspace_maintenance_run
    )
    policy_bundle((removed, "admin", "owner"))
    owner = User(username="maintenance-owner", password_hash="unused")
    actor = User(username="maintenance-admin", password_hash="unused")
    async_db.add_all([owner, actor])
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=actor.id, role=WorkspaceRole.admin)
    )
    await async_db.commit()
    if maintenance_allowed:
        assert await dispatch_workspace_reindex(async_db, actor, workspace.id)
    else:
        with pytest.raises(PermissionDenied):
            await dispatch_workspace_reindex(async_db, actor, workspace.id)


@pytest.mark.anyio
@pytest.mark.parametrize("metadata_allowed", [False, True])
async def test_project_choices_and_commands_do_not_infer_independent_grants(
    async_db, async_session_factory, tmp_path, monkeypatch, policy_bundle, metadata_allowed
):
    removed = (
        ResourceAction.project_membership_manage
        if metadata_allowed
        else ResourceAction.project_update
    )
    policy_bundle((removed, "admin" if metadata_allowed else "editor", "owner"))
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    project = await create_project(async_db, owner, item.workspace_id, "Independent choices")
    actor = User(username="project-admin", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(workspace_id=item.workspace_id, user_id=actor.id, role=WorkspaceRole.admin)
    )
    await async_db.commit()
    grant = await create_api_token(async_db, actor, "Project choices", expires_in_days=1)
    client.headers["Authorization"] = f"Bearer {grant.raw_token}"
    url = f"/api/v1/workspaces/{item.workspace_id}/projects/{project.id}"
    try:
        response = await client.get(url)
        assert response.status_code == 200
        view = response.json()
        assert view["allowed_participation_changes"] == (
            [ProjectParticipation.workspace.value, ProjectParticipation.open.value]
            if metadata_allowed
            else []
        )
        assert ("project.update" in view["authorization"]["allowed"]) is metadata_allowed
        metadata = await client.patch(url, json={"name": "Metadata"})
        assert metadata.status_code == (200 if metadata_allowed else 403)
        participation = await client.patch(url, json={"participation": "managed"})
        assert participation.status_code == 403
        await async_db.refresh(project)
        assert project.name == ("Metadata" if metadata_allowed else "Independent choices")
        assert project.participation is ProjectParticipation.workspace
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("lock", [None, "shared", "update"])
async def test_project_lock_is_explicit_at_the_command_boundary(async_db, lock):
    owner = User(username="locking-owner", password_hash="unused")
    async_db.add(owner)
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, owner)
    project = Project(workspace_id=workspace.id, name="Lock", created_by=owner.id)
    async_db.add(project)
    await async_db.commit()
    locks = []

    def record(execution):
        statement = execution.statement
        if execution.is_select and statement._for_update_arg is not None:
            locks.append(statement)

    event.listen(async_db.sync_session, "do_orm_execute", record)
    try:
        await require_project_context(
            async_db, owner, workspace.id, project.id, ResourceAction.workspace_read, lock=lock
        )
    finally:
        event.remove(async_db.sync_session, "do_orm_execute", record)
    if lock is None:
        assert not locks
        with pytest.raises(ValueError, match="explicitly select"):
            await require_project_context(
                async_db, owner, workspace.id, project.id, ResourceAction.project_update
            )
    else:
        assert len(locks) == 2
        assert locks[0]._for_update_arg.read is True
        assert locks[1]._for_update_arg.read is (lock == "shared")
