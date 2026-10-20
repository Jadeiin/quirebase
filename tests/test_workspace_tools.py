from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from app_helpers import json_payload
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from test_http import authenticated_async_client
from workspace_helpers import provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.models import (
    FileRevision,
    FileRevisionProcessingState,
    Item,
    ItemTag,
    LoginSession,
    Project,
    ProjectParticipant,
    ProjectParticipation,
    SystemSetting,
    Tag,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)


@pytest.mark.anyio
async def test_projects_have_a_dedicated_workspace(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        created = await client.post(
            f"{workspace_base}/projects",
            json=json_payload({"name": "Review queue", "participation": "open"}),
        )
        project = await db.scalar(select(Project).where(Project.name == "Review queue"))
        assert project is not None
        assert created.status_code == 201
        assert created.json()["id"] == str(project.id)
        listing = await client.get(f"{workspace_base}/projects")
        assert [row["name"] for row in listing.json()["items"]] == ["Review queue"]
        detail = await client.get(f"{workspace_base}/projects/{project.id}")
        assert detail.json()["name"] == "Review queue"
        updated = await client.patch(
            f"{workspace_base}/projects/{project.id}",
            json=json_payload({
                "name": "Review complete",
                "description": "Reviewed together",
                "participation": "workspace",
            }),
        )
        assert updated.status_code == 200
        refreshed = await client.get(f"{workspace_base}/projects/{project.id}")
        assert {key: refreshed.json()[key] for key in ("name", "description", "participation")} == {
            "name": "Review complete",
            "description": "Reviewed together",
            "participation": "workspace",
        }
        membership = await db.scalar(
            select(ProjectParticipant).where(
                ProjectParticipant.workspace_id == item.workspace_id,
                ProjectParticipant.project_id == project.id,
                ProjectParticipant.user_id == item.created_by,
            )
        )
        assert membership is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_participant_directory_tracks_account_activation(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    owner.role = "administrator"
    target = User(username="participant-candidate", password_hash="unused")
    async_db.add(target)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id, user_id=target.id, role=WorkspaceRole.editor
        )
    )
    project = Project(
        workspace_id=item.workspace_id,
        name="Managed participants",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
    )
    async_db.add(project)
    await async_db.commit()
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    target_status = f"/api/v1/admin/users/{target.id}/status"
    participant_path = f"{workspace_base}/projects/{project.id}/participants"
    try:
        directory = await client.get(f"{workspace_base}/members")
        assert directory.status_code == 200
        assert str(target.id) in {row["user_id"] for row in directory.json()["items"]}

        disabled = await client.put(target_status, json=json_payload({"active": False}))
        assert disabled.status_code == 200
        directory = await client.get(f"{workspace_base}/members")
        assert directory.status_code == 200
        assert str(target.id) not in {row["user_id"] for row in directory.json()["items"]}
        governance = await client.get(f"{workspace_base}/governance/members")
        assert governance.status_code == 200
        member = next(row for row in governance.json()["items"] if row["user_id"] == str(target.id))
        assert member["state"] == "active"
        rejected = await client.post(
            participant_path, json=json_payload({"username": target.username})
        )
        assert rejected.status_code == 404

        reactivated = await client.put(target_status, json=json_payload({"active": True}))
        assert reactivated.status_code == 200
        directory = await client.get(f"{workspace_base}/members")
        assert directory.status_code == 200
        assert str(target.id) in {row["user_id"] for row in directory.json()["items"]}
        added = await client.post(
            participant_path, json=json_payload({"username": target.username})
        )
        assert added.status_code == 200
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_tools_detect_title_duplicates_and_manage_owned_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        duplicate = Item(
            workspace_id=item.workspace_id,
            created_by=item.created_by,
            work={
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": item.work["title"],
                "identifiers": [{"identifier_type": "DOI", "identifier": "10.1000/same"}],
            },
        )
        item.work = {
            **item.work,
            "identifiers": [
                *item.work.get("identifiers", []),
                {"identifier_type": "DOI", "identifier": "10.1000/first"},
            ],
        }
        tag = Tag(
            workspace_id=item.workspace_id,
            name="Old tag",
            created_by=item.created_by,
        )
        db.add_all([duplicate, tag])
        await db.flush()
        db.add(ItemTag(workspace_id=item.workspace_id, item_id=item.id, tag_id=tag.id))
        await db.commit()

        tools = await client.get(f"{workspace_base}/duplicates?mode=title")
        assert tools.status_code == 200
        assert len(tools.json()["groups"]) == 1
        assert {row["id"] for row in tools.json()["groups"][0]} == set(
            map(str, {item.id, duplicate.id})
        )
        assert tools.json()["scanned"] == 2
        assert set(tools.json()) == {"groups", "scanned"}
        unhashed = await client.get(f"{workspace_base}/duplicates?mode=file")
        assert unhashed.status_code == 200
        assert unhashed.json() == {"groups": [], "scanned": 0}
        checksum = "sha256:" + "a" * 64
        revision.file = FileObject(**(revision.file.to_dict() | {"checksum": checksum}))
        flag_modified(revision, "file")
        revision.processing_state = FileRevisionProcessingState.ready
        db.add(
            FileRevision(
                workspace_id=item.workspace_id,
                item_id=duplicate.id,
                created_by=item.created_by,
                processing_state=FileRevisionProcessingState.ready,
                file=FileObject(
                    backend="documents", filename=f"{uuid4().hex}.pdf", checksum=checksum
                ),
            )
        )
        await db.commit()
        same_pdf = await client.get(f"{workspace_base}/duplicates?mode=file")
        assert same_pdf.status_code == 200
        assert same_pdf.json()["scanned"] == 2
        assert len(same_pdf.json()["groups"]) == 1
        assert {row["id"] for row in same_pdf.json()["groups"][0]} == {
            str(item.id),
            str(duplicate.id),
        }
        for query in ("", "?mode=", "?mode=unknown", "?mode=similar", "?mode=author"):
            invalid_mode = await client.get(f"{workspace_base}/duplicates{query}")
            assert invalid_mode.status_code == 422
        tags = await client.get(f"{workspace_base}/tags")
        assert tags.json()["items"][0]["name"] == "Old tag"
        assert tags.json()["items"][0]["accessible_item_count"] == 1

        # Tag filters identify a single Tag, even when another Tag is named after its UUID.
        misleading_tag = Tag(
            workspace_id=item.workspace_id, name=str(tag.id), created_by=item.created_by
        )
        db.add(misleading_tag)
        await db.flush()
        db.add(
            ItemTag(workspace_id=item.workspace_id, item_id=duplicate.id, tag_id=misleading_tag.id)
        )
        await db.commit()
        filtered_by_id = await client.get(f"{workspace_base}/items", params={"tag": tag.id})
        assert filtered_by_id.status_code == 200
        assert [row["id"] for row in filtered_by_id.json()["items"]] == [str(item.id)]

        filtered_by_name = await client.get(f"{workspace_base}/items", params={"tag": "Old tag"})
        assert filtered_by_name.status_code == 422
        invalid_facets = await client.get(
            f"{workspace_base}/items/facets", params={"tag": "Old tag"}
        )
        assert invalid_facets.status_code == 422

        orphan_tag = Tag(
            workspace_id=item.workspace_id,
            name="Orphan tag",
            created_by=item.created_by,
        )
        db.add(orphan_tag)
        await db.commit()

        tools_tags = await client.get(f"{workspace_base}/tags")
        assert tools_tags.status_code == 200
        assert (
            next(row for row in tools_tags.json()["items"] if row["name"] == "Orphan tag")[
                "accessible_item_count"
            ]
            == 0
        )

        target_tag = Tag(
            workspace_id=item.workspace_id,
            name="Reviewed topic",
            created_by=item.created_by,
        )
        db.add(target_tag)
        await db.commit()
        merged = await client.post(
            f"{workspace_base}/tags/merge",
            json=json_payload({
                "source_tag_id": tag.id,
                "target_tag_id": target_tag.id,
            }),
        )
        assert merged.status_code == 200
        assert await db.get(Tag, tag.id) is None
        assert await db.get(ItemTag, (item.id, target_tag.id)) is not None

        renamed = await client.patch(
            f"{workspace_base}/tags/{target_tag.id}",
            json=json_payload({"name": "Reviewed"}),
        )
        assert renamed.status_code == 200
        await db.refresh(target_tag)
        assert target_tag.name == "Reviewed"

        removed = await client.delete(f"{workspace_base}/tags/{target_tag.id}")
        assert removed.status_code == 200
        assert await db.get(Tag, target_tag.id) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize("invitation_role", ["editor", "admin"])
async def test_workspace_invitation_uses_username_and_global_acceptance_route(
    async_db, async_session_factory, tmp_path, monkeypatch, invitation_role
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    invitee = User(username="workspace-invitee", password_hash="unused")
    governed_member = User(username="workspace-governed-member", password_hash="unused")
    async_db.add_all([invitee, governed_member])
    await async_db.flush()
    await provision_initial_workspace(async_db, invitee)
    async_db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id,
            user_id=governed_member.id,
            role=WorkspaceRole.editor,
            invited_by=item.created_by,
        )
    )
    invitation_session = "workspace-invitee-session"
    async_db.add(
        LoginSession(
            token_hash=token_hash(invitation_session),
            user_id=invitee.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await async_db.commit()
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        members = await client.get(f"{workspace_base}/members")
        assert members.status_code == 200
        assert set(members.json()["items"][0]) == {"user_id", "username", "role"}
        assert (
            next(row for row in members.json()["items"] if row["user_id"] == str(item.created_by))[
                "username"
            ]
            == "reader"
        )

        governance_members = await client.get(f"{workspace_base}/governance/members")
        assert governance_members.status_code == 200
        assert set(governance_members.json()["items"][0]) == {
            "membership_id",
            "user_id",
            "username",
            "role",
            "state",
            "joined_at",
            "authorization",
            "allowed_roles",
        }
        governed_view = next(
            row
            for row in governance_members.json()["items"]
            if row["user_id"] == str(governed_member.id)
        )
        assert set(governed_view["allowed_roles"]) == {"admin", "reviewer", "viewer"}
        assert set(governed_view["authorization"]["allowed"]) == {
            "workspace_member.transfer_ownership",
            "workspace_member.suspend",
            "workspace_member.terminate",
        }

        before_invitation = datetime.now(UTC)
        created = await client.post(
            f"{workspace_base}/invitations",
            json=json_payload({
                "username": invitee.username,
                "role": invitation_role,
            }),
        )
        assert created.status_code == 201
        assert created.json()["username"] == invitee.username
        assert created.json()["role"] == invitation_role
        expiry = datetime.fromisoformat(created.json()["expires_at"])
        assert before_invitation + timedelta(days=7) <= expiry
        assert expiry <= datetime.now(UTC) + timedelta(days=7)
        token = created.json()["token"]

        details = await client.get(f"/api/v1/invitations/{token}")
        assert details.status_code == 200
        assert details.json()["kind"] == "workspace"
        assert details.json()["username"] == invitee.username
        assert details.json()["workspace_name"]

        client.cookies.set(get_settings().session_cookie, invitation_session)
        accepted = await client.post(
            f"/api/v1/workspace-invitations/{token}/accept",
        )
        assert accepted.status_code == 200
        assert accepted.json() == {"workspace_id": str(item.workspace_id)}
        member = await async_db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == item.workspace_id,
                WorkspaceMember.user_id == invitee.id,
            )
        )
        assert member is not None and member.state is WorkspaceMemberState.active
        assert member.role is WorkspaceRole(invitation_role)
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_account_and_admin_workspace_apis(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        sessions = await client.get("/api/v1/account")
        assert sessions.status_code == 200
        assert len(sessions.json()["sessions"]) == 1
        assert sessions.json()["sessions"][0]["current"] is True

        workspaces = await client.get("/api/v1/workspaces")
        assert workspaces.status_code == 200
        current_workspace = workspaces.json()["items"][0]
        assert current_workspace["current_role"] == "owner"
        assert "role" not in current_workspace
        assert "workspace.read" in current_workspace["authorization"]["allowed"]
        assert set(current_workspace["allowed_invitation_roles"]) == {
            "admin",
            "editor",
            "reviewer",
            "viewer",
        }
        assert "project.create" not in current_workspace["authorization"]["allowed"]
        assert set(current_workspace["allowed_project_participations"]) == {
            "workspace",
            "open",
            "managed",
        }
        assert set(current_workspace["authorization"]) == {"allowed"}

        user = await db.get(User, item.created_by)
        assert user is not None
        db.add(SystemSetting(key="workspace_creation_policy", value="admins_only"))
        await db.commit()
        availability = await client.get("/api/v1/workspaces/creation-availability")
        assert availability.status_code == 200
        assert availability.json() == {"allowed": False, "owner_username_required": True}

        user.role = "administrator"
        await db.commit()
        availability = await client.get("/api/v1/workspaces/creation-availability")
        assert availability.status_code == 200
        assert availability.json() == {"allowed": True, "owner_username_required": True}

        missing_owner = await client.post(
            "/api/v1/workspaces", json=json_payload({"name": "Created without an owner"})
        )
        assert missing_owner.status_code == 422

        created = await client.post(
            "/api/v1/workspaces",
            json=json_payload({"name": "Created in UI", "owner_username": user.username}),
        )
        assert created.status_code == 201
        created_workspace = next(
            workspace
            for workspace in (await client.get("/api/v1/workspaces")).json()["items"]
            if workspace["id"] == created.json()["id"]
        )
        assert created_workspace["name"] == "Created in UI"
        assert created_workspace["current_role"] == "owner"

        creation_policy = await db.scalar(
            select(SystemSetting).where(SystemSetting.key == "workspace_creation_policy")
        )
        assert creation_policy is not None
        creation_policy.value = "members_allowed"
        await db.commit()
        availability = await client.get("/api/v1/workspaces/creation-availability")
        assert availability.status_code == 200
        assert availability.json() == {"allowed": True, "owner_username_required": False}

        admin = await client.get("/api/v1/admin/overview")
        assert admin.status_code == 200
        assert admin.json()["user_count"] == 1
        assert admin.json()["pending_invitation_count"] == 0
    finally:
        await client.aclose()
        get_settings.cache_clear()
