import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx2
import pytest
from advanced_alchemy.types import FileObject
from app_helpers import create_web_test_app, json_payload
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from storage_helpers import local_object_path, put_pdf_object
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.errors import VersionConflict
from quirebase.core.storage import ObjectMetadata, ObjectSuffix, get_object_store
from quirebase.documents import workflows as document_workflows
from quirebase.library import ItemMetadata, request_item_tag_recommendation, revise_item_metadata
from quirebase.models import (
    Attachment,
    AttachmentRole,
    AuditEvent,
    FileRevision,
    Item,
    ItemTagRecommendation,
    LoginSession,
    Project,
    ProjectItem,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.search import search_index
from quirebase.web.api import admin as admin_api
from quirebase.web.api import workspaces as workspace_api
from quirebase.workspaces import permanently_delete_workspace


async def authenticated_async_client(db, session_factory, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    raw = "test-session-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(
        workspace_id=fixture_workspace_id(user),
        title="Paper",
        created_by=user.id,
    )
    db.add_all([login, item])
    await db.flush()
    key, size = await put_pdf_object(b"%PDF-1.4\ntest", 100)
    revision = FileRevision(
        workspace_id=fixture_workspace_id(user),
        item_id=item.id,
        page_count=1,
        page_geometry=[[0, 0, 300, 400]],
        processing_state="ready",
        created_by=user.id,
        file=FileObject(
            backend="documents",
            filename=key,
            size=size,
            content_type="application/pdf",
            metadata={"original_name": "paper.pdf"},
        ),
    )
    db.add(revision)
    await db.commit()

    test_app = create_web_test_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Origin": "http://testserver",
        },
        follow_redirects=True,
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return client, item, revision


@pytest.mark.anyio
@pytest.mark.parametrize("surface", ["list", "detail", "admin"])
async def test_workspace_read_tolerates_deletion_before_owner_lookup(
    async_db, async_session_factory, tmp_path, monkeypatch, surface
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id, owner_id = item.workspace_id, item.created_by
    workspace = await async_db.get(Workspace, workspace_id)
    workspace.state = WorkspaceState.archived
    workspace.archived_at = datetime.now(UTC) - timedelta(
        days=get_settings().workspace_delete_retention_days + 1
    )
    retained = Workspace(name="Retained Workspace", created_by=owner_id)
    async_db.add(retained)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(workspace_id=retained.id, user_id=owner_id, role=WorkspaceRole.owner)
    )
    if surface == "admin":
        owner = await async_db.get(User, owner_id)
        owner.role = "administrator"
    await async_db.commit()

    detail = surface == "detail"
    if surface == "admin":
        url, api = "/api/v1/admin/workspaces", admin_api
    else:
        url = f"/api/v1/workspaces/{workspace_id}" if detail else "/api/v1/workspaces"
        api = workspace_api
    owner_lookup = api.workspace_owner_ids

    async def delete_before_owner_lookup(db, workspace_ids):
        # The handler has already read the Workspace or resolved its access context.
        assert workspace_id in workspace_ids
        async with async_session_factory() as delete_db:
            owner = await delete_db.get(User, owner_id)
            await permanently_delete_workspace(delete_db, owner, workspace_id)
        return await owner_lookup(db, workspace_ids)

    try:
        before = await client.get(url)
        assert before.status_code == 200
        if detail:
            assert before.json()["owner_id"] == str(owner_id)
        else:
            assert {
                view["id"]
                for view in (before.json()["items"] if surface == "list" else before.json())
            } == set(map(str, {workspace_id, retained.id}))

        monkeypatch.setattr(api, "workspace_owner_ids", delete_before_owner_lookup)
        response = await client.get(url)
        if detail:
            assert response.status_code == 404
        else:
            assert response.status_code == 200
            assert [
                (view["id"], view["owner_id"])
                for view in (response.json()["items"] if surface == "list" else response.json())
            ] == [(str(retained.id), str(owner_id))]
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_managed_project_nonmember_cannot_discover_project_contexts(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    owner = await async_db.get(User, item.created_by)
    assert owner is not None
    workspace_id = item.workspace_id
    outsider = User(username="managed-http-outsider", password_hash="unused")
    async_db.add(outsider)
    await async_db.flush()
    project = Project(
        workspace_id=workspace_id,
        name="Hidden Project",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
    )
    async_db.add(project)
    await async_db.flush()
    async_db.add_all([
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=outsider.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        ),
        LoginSession(
            token_hash=token_hash("managed-outsider-session"),
            user_id=outsider.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        ProjectItem(
            workspace_id=workspace_id,
            project_id=project.id,
            item_id=item.id,
            added_by=owner.id,
        ),
    ])
    await async_db.commit()
    client.cookies.set(get_settings().session_cookie, "managed-outsider-session")
    base = f"/api/v1/workspaces/{workspace_id}"
    missing_id = str(uuid4())

    try:
        for method, path in (
            ("GET", "/projects/{project_id}"),
            ("GET", "/projects/{project_id}/discussions"),
            ("PUT", f"/projects/{{project_id}}/items/{item.id}"),
            (
                "GET",
                f"/items/{item.id}/annotations?revision_id={revision.id}&project_id={{project_id}}",
            ),
        ):
            hidden = await client.request(method, base + path.format(project_id=project.id))
            missing = await client.request(method, base + path.format(project_id=missing_id))
            assert hidden.status_code == missing.status_code == 404
            assert hidden.json() == missing.json()

        listed = await client.get(base + "/projects?view=all")
        organize = await client.get(base + f"/items/{item.id}/organize")
        viewer = await client.get(base + f"/items/{item.id}/revisions/{revision.id}/viewer")
        assert listed.status_code == organize.status_code == viewer.status_code == 200
        assert project.id not in {row["id"] for row in listed.json()["items"]}
        assert project.id not in {row["id"] for row in organize.json()["projects"]}
        assert project.id not in {row["id"] for row in viewer.json()["projects"]}
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "availability", ["missing", "deleted", "nonmember", "suspended", "terminated"]
)
@pytest.mark.parametrize("surface", ["detail", "projects", "create"])
async def test_inaccessible_workspace_responses_do_not_expose_existence(
    async_db, async_session_factory, tmp_path, monkeypatch, availability, surface
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = str(uuid4())
    if availability != "missing":
        owner = User(username="unavailable-owner", password_hash="unused")
        async_db.add(owner)
        await async_db.flush()
        workspace = await provision_initial_workspace(async_db, owner)
        workspace_id = workspace.id
        if availability == "deleted":
            workspace.state = WorkspaceState.deleted
        if availability in {"suspended", "terminated"}:
            async_db.add(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=item.created_by,
                    role=WorkspaceRole.viewer,
                    state=(
                        WorkspaceMemberState.suspended
                        if availability == "suspended"
                        else WorkspaceMemberState.active
                    ),
                    terminated_at=datetime.now(UTC) if availability == "terminated" else None,
                )
            )
        await async_db.commit()
    base = f"/api/v1/workspaces/{workspace_id}"
    try:
        response = (
            await client.post(f"{base}/projects", json=json_payload({"name": "Rejected"}))
            if surface == "create"
            else await client.get(base if surface == "detail" else f"{base}/projects")
        )
        assert response.status_code == 404
        assert response.json() == {
            "code": "workspace_unavailable",
            "message": "Workspace not found",
        }
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_cross_workspace_copy_api_checks_target_membership_and_resource_action(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, source, source_revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    target_owner = User(username="copy-target-owner", password_hash="unused")
    async_db.add(target_owner)
    await async_db.flush()
    await provision_initial_workspace(async_db, target_owner)
    await async_db.commit()
    target_workspace_id = fixture_workspace_id(target_owner)
    url = f"/api/v1/workspaces/{source.workspace_id}/items/{source.id}/copy"
    request = {"target_workspace_id": target_workspace_id}
    headers = {"X-CSRF-Token": "test-csrf"}

    try:
        missing = await client.post(url, headers=headers, json=json_payload(request))
        assert missing.status_code == 404
        assert missing.json()["code"] == "workspace_unavailable"
        nonexistent = await client.post(
            url, json=json_payload({"target_workspace_id": str(uuid4())})
        )
        assert nonexistent.status_code == missing.status_code
        assert nonexistent.json() == missing.json()

        membership = WorkspaceMember(
            workspace_id=target_workspace_id,
            user_id=source.created_by,
            role=WorkspaceRole.viewer,
            invited_by=target_owner.id,
        )
        async_db.add(membership)
        await async_db.commit()

        viewer = await client.post(url, headers=headers, json=json_payload(request))
        assert viewer.status_code == 403
        assert viewer.json()["code"] == "permission_denied"

        membership.role = WorkspaceRole.editor
        await async_db.commit()
        copied = await client.post(url, headers=headers, json=json_payload(request))
        assert copied.status_code == 201
        copy_view = copied.json()
        assert set(copy_view) == {
            "source_workspace_id",
            "source_item_id",
            "target_workspace_id",
            "target_item_id",
        }
        assert copy_view["source_workspace_id"] == str(source.workspace_id)
        assert copy_view["source_item_id"] == str(source.id)
        assert copy_view["target_workspace_id"] == str(target_workspace_id)
        copied_id = copy_view["target_item_id"]
        copied_item = await async_db.get(Item, copied_id)
        copied_revision = await async_db.scalar(
            select(FileRevision).where(FileRevision.item_id == copied_id)
        )
        assert copied_item is not None
        assert copied_item.workspace_id == target_workspace_id
        assert copied_revision is not None
        assert copied_revision.file.path != source_revision.file.path
        assert await get_object_store().exists(copied_revision.file.path)
        events = (
            await async_db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_((
                        "workspace.item.copy.export",
                        "workspace.item.copy.import",
                    ))
                )
            )
        ).all()
        assert {event.workspace_id for event in events} == {
            source.workspace_id,
            target_workspace_id,
        }
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("lifecycle", ["archived", "governance-frozen"])
async def test_read_only_workspace_pdf_viewer_disables_annotation_edits(
    async_db, async_session_factory, tmp_path, monkeypatch, lifecycle
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace = await async_db.get(Workspace, item.workspace_id)
    assert workspace is not None
    if lifecycle == "archived":
        workspace.state = WorkspaceState.archived
    else:
        workspace.governance_frozen_at = datetime.now(UTC)
    await async_db.commit()
    base = f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}"
    try:
        viewer = await client.get(f"{base}/revisions/{revision.id}/viewer")
        assert viewer.status_code == 200
        assert viewer.json()["editable"] is False
        content = await client.get(f"{base}/revisions/{revision.id}/content")
        assert content.status_code == 200
        created = await client.post(
            f"{base}/annotations",
            json=json_payload({
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "private",
                "body": "Cannot save",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 20},
                },
            }),
        )
        assert created.status_code == 409
        assert created.json()["code"] == "workspace_lifecycle_error"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_pdf_range_and_annotation_api(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        viewer = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/viewer"
        )
        assert viewer.status_code == 200
        assert viewer.json()["revision"]["id"] == str(revision.id)
        assert viewer.json()["revision"]["page_geometry"] == [[0, 0, 300, 400]]
        assert viewer.json()["editable"] is True
        assert viewer.json()["annotation_author"] == "reader"
        assert viewer.json()["revision"]["content_url"] == (
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/content"
        )

        content = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert content.status_code == 206
        assert content.content == b"%PDF-"
        assert content.headers["content-range"].startswith("bytes 0-4/")
        assert content.headers["etag"].startswith('"')
        assert content.headers["etag"].endswith('"')
        assert not content.headers["etag"].startswith('""')

        empty_range = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=-"},
        )
        assert empty_range.status_code == 416
        assert empty_range.headers["content-range"].startswith("bytes */")

        project = Project(
            workspace_id=item.workspace_id,
            name="Annotation replies",
            created_by=item.created_by,
        )
        db.add(project)
        await db.flush()
        db.add(
            ProjectItem(
                workspace_id=item.workspace_id,
                project_id=project.id,
                item_id=item.id,
                added_by=item.created_by,
            )
        )
        await db.commit()

        created = await client.post(
            f"{workspace_base}/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "highlight",
                "scope": "project",
                "project_id": project.id,
                "selected_text": "test",
                "payload": {
                    "type": "highlight",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 10},
                    "style": {"stroke_color": "#FFEB33", "opacity": 0.35},
                    "segment_rects": [{"x": 10, "y": 10, "width": 20, "height": 10}],
                },
            }),
        )
        assert created.status_code == 201
        annotation = created.json()
        assert annotation["mine"] is True
        assert annotation["replies"] == []

        reply_id = str(uuid4())
        replied = await client.post(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/replies",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({"id": reply_id, "body": "Collaborative reply"}),
        )
        assert replied.status_code == 201
        reply = replied.json()
        assert reply["annotation_id"] == annotation["id"]
        assert reply["body"] == "Collaborative reply"
        listed_with_reply = await client.get(
            f"{workspace_base}/items/{item.id}/annotations",
            params={"revision_id": revision.id, "project_id": project.id},
        )
        listed_reply = listed_with_reply.json()["annotations"][0]["replies"][0]
        assert listed_reply["id"] == reply["id"]
        assert listed_reply["body"] == reply["body"]
        updated_reply = await client.patch(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({"version": reply["version"], "body": "Updated reply"}),
        )
        assert updated_reply.status_code == 200
        assert updated_reply.json()["version"] == 2
        assert updated_reply.json()["body"] == "Updated reply"
        deleted_reply = await client.delete(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 2},
        )
        assert deleted_reply.status_code == 200
        restored_reply = await client.post(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 3},
        )
        assert restored_reply.status_code == 200
        assert restored_reply.json()["version"] == 4
        deleted_reply_again = await client.delete(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/replies/{reply_id}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": 4},
        )
        assert deleted_reply_again.status_code == 200

        duplicate = await client.post(
            f"{workspace_base}/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({
                "id": annotation["id"],
                "revision_id": revision.id,
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": annotation["body"],
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            }),
        )
        assert duplicate.status_code == 409

        other_item = Item(
            workspace_id=item.workspace_id,
            title="Different paper",
            created_by=item.created_by,
        )
        db.add(other_item)
        await db.commit()
        mismatched = await client.get(
            f"{workspace_base}/items/{other_item.id}/revisions/{revision.id}/export"
        )
        assert mismatched.status_code == 404

        revision.file.update_metadata({"original_name": "论文.pdf"})
        flag_modified(revision, "file")
        await db.commit()
        unicode_content = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/content"
        )
        unicode_range = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        unicode_download = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/export",
            params={"include_annotations": False},
        )
        assert unicode_content.status_code == 200
        assert unicode_range.status_code == 206
        assert unicode_download.status_code == 200
        for response in (unicode_content, unicode_range, unicode_download):
            assert (
                "filename*=utf-8''%E8%AE%BA%E6%96%87.pdf" in response.headers["content-disposition"]
            )
        revision.file.update_metadata({"original_name": "paper.pdf"})
        flag_modified(revision, "file")
        await db.commit()

        exported = await client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/export",
            params={"include_annotations": False},
        )
        assert exported.status_code == 200
        assert "paper.pdf" in exported.headers["content-disposition"]
        events = list(
            await db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "item.download_revision_pdf",
                    AuditEvent.target_id == str(revision.id),
                )
            )
        )
        details = [event.detail for event in events]
        assert any(detail["item_id"] == str(item.id) for detail in details)
        assert all(event.actor_id == item.created_by for event in events)

        underlined = await client.post(
            f"{workspace_base}/items/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "underline",
                "scope": "private",
                "selected_text": "underlined text",
                "body": "underline comment",
                "payload": {
                    "type": "underline",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 10},
                    "style": {"stroke_color": "#FF5959", "opacity": 0.9},
                    "segment_rects": [{"x": 10, "y": 10, "width": 20, "height": 10}],
                },
            }),
        )
        assert underlined.status_code == 201
        assert underlined.json()["kind"] == "underline"
        assert underlined.json()["payload"]["style"]["stroke_color"] == "#FF5959"

        conflict = await client.patch(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json=json_payload({
                "version": 99,
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": annotation["body"],
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            }),
        )
        assert conflict.status_code == 409

        deleted = await client.delete(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"]},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        stale_restore = await client.post(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"]},
        )
        assert stale_restore.status_code == 409
        restored = await client.post(
            f"{workspace_base}/items/{item.id}/annotations/{annotation['id']}/restore",
            headers={"X-CSRF-Token": "test-csrf"},
            params={"version": annotation["version"] + 1},
        )
        assert restored.status_code == 200
        assert restored.json()["version"] == annotation["version"] + 2
        assert restored.json()["replies"] == []
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "annotation.delete",
                AuditEvent.target_id == str(annotation["id"]),
            )
        )
        assert await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "annotation.restore",
                AuditEvent.target_id == str(annotation["id"]),
            )
        )
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize("role", [WorkspaceRole.viewer, WorkspaceRole.reviewer])
@pytest.mark.parametrize("project_state", [ProjectState.active, ProjectState.archived])
async def test_pdf_viewer_creation_permissions_match_annotation_scope(
    async_db, async_session_factory, tmp_path, monkeypatch, role, project_state
):
    db = async_db
    owner_client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    viewer = User(username="annotation-viewer", password_hash="unused")
    project = Project(
        workspace_id=item.workspace_id,
        name="Readable annotations",
        created_by=item.created_by,
        participation="managed",
        state=project_state,
    )
    db.add_all([viewer, project])
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id,
            user_id=viewer.id,
            role=role,
            invited_by=item.created_by,
        )
    )
    db.add_all([
        ProjectItem(
            workspace_id=item.workspace_id,
            project_id=project.id,
            item_id=item.id,
            added_by=item.created_by,
        ),
        ProjectParticipant(
            workspace_id=item.workspace_id,
            project_id=project.id,
            user_id=viewer.id,
        ),
        LoginSession(
            token_hash=token_hash("annotation-viewer-session"),
            user_id=viewer.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ])
    await db.commit()

    try:
        owner_client.cookies.set(
            get_settings().session_cookie,
            "annotation-viewer-session",
        )
        viewer = await owner_client.get(
            f"{workspace_base}/items/{item.id}/revisions/{revision.id}/viewer"
        )
        created = await owner_client.post(
            f"{workspace_base}/items/{item.id}/annotations",
            json=json_payload({
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "private",
                "body": "Reader note",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 20},
                },
            }),
        )

        assert viewer.status_code == 200
        assert viewer.json()["editable"] is True
        project_editable = role is WorkspaceRole.reviewer and project_state is ProjectState.active
        assert viewer.json()["projects"] == json_payload([
            {"id": project.id, "name": project.name, "editable": project_editable}
        ])
        assert created.status_code == 201
        project_created = await owner_client.post(
            f"{workspace_base}/items/{item.id}/annotations",
            json=json_payload({
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "project",
                "project_id": project.id,
                "body": "Project note",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 10, "width": 20, "height": 20},
                },
            }),
        )
        assert project_created.status_code == (
            201 if project_editable else 403 if role is WorkspaceRole.viewer else 409
        )
    finally:
        await owner_client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_overview_uses_the_ready_revision_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"\x89PNG\r\n\x1a\nthumbnail", max_bytes=100
    )
    revision.thumbnail = FileObject(
        backend="documents", filename=thumbnail.key, content_type="image/png"
    )
    await async_db.commit()
    thumbnail_url = f"{workspace_base}/items/{item.id}/thumbnail"

    try:
        response = await client.get(thumbnail_url)

        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == b"\x89PNG\r\n\x1a\nthumbnail"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_thumbnail_revalidates_all_if_none_match_forms(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"cached-thumbnail", max_bytes=100
    )
    revision.thumbnail = FileObject(
        backend="documents", filename=thumbnail.key, content_type="image/png"
    )
    await async_db.commit()
    thumbnail_url = f"{workspace_base}/items/{item.id}/thumbnail"

    try:
        initial = await client.get(thumbnail_url)
        etag = initial.headers["etag"]

        for validator in (
            "*",
            f'"other", {etag}',
            f"W/{etag}",
            f'"opaque,tag", W/{etag}',
        ):
            response = await client.get(thumbnail_url, headers={"If-None-Match": validator})
            assert response.status_code == 304
            assert response.headers["etag"] == etag
            assert response.headers["cache-control"] == "private, no-cache"
            assert response.content == b""

        mismatch = await client.get(
            thumbnail_url,
            headers={"If-None-Match": '"first", W/"second"'},
        )
        assert mismatch.status_code == 200
        assert mismatch.content == b"cached-thumbnail"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_thumbnail_fetches_the_source_checked_for_cache_metadata(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from quirebase.web.api import documents as documents_api

    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    original = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"original-thumbnail", max_bytes=100
    )
    replacement = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"newer-thumbnail-with-a-different-size", max_bytes=100
    )
    revision.thumbnail = FileObject(
        backend="documents", filename=original.key, content_type="image/png"
    )
    await async_db.commit()
    checked_metadata: ObjectMetadata | None = None
    original_head = documents_api.head_item_thumbnail

    async def switch_source_after_head(source):
        nonlocal checked_metadata
        checked_metadata = await original_head(source)
        revision.thumbnail = FileObject(
            backend="documents", filename=replacement.key, content_type="image/png"
        )
        await async_db.flush()
        return checked_metadata

    monkeypatch.setattr(documents_api, "head_item_thumbnail", switch_source_after_head)

    try:
        response = await client.get(f"{workspace_base}/items/{item.id}/thumbnail")

        assert checked_metadata is not None
        assert response.status_code == 200
        assert response.content == b"original-thumbnail"
        assert response.headers["content-length"] == str(checked_metadata.size)
        assert response.headers["etag"] == checked_metadata.etag
        assert response.headers["cache-control"] == "private, no-cache"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_overview_omits_a_missing_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    thumbnail_url = f"{workspace_base}/items/{item.id}/thumbnail"

    try:
        response = await client.get(thumbnail_url)
        assert response.status_code == 404
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_deleting_latest_pdf_revision_removes_its_files_and_falls_back_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, old_revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    old_thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"old-thumbnail", max_bytes=100
    )
    old_revision.thumbnail = FileObject(
        backend="documents", filename=old_thumbnail.key, content_type="image/png"
    )
    old_revision.full_text = "fallbacksearchtoken"
    key, size = await put_pdf_object(b"%PDF-1.4\nnewer", 100)
    new_revision = FileRevision(
        workspace_id=item.workspace_id,
        item_id=item_id,
        page_count=1,
        page_geometry=[[0, 0, 300, 400]],
        processing_state="ready",
        full_text="deletedsearchtoken",
        created_by=item.created_by,
        created_at=old_revision.created_at + timedelta(seconds=1),
        file=FileObject(
            backend="documents",
            filename=key,
            size=size,
            content_type="application/pdf",
            metadata={"original_name": "newer.pdf"},
        ),
    )
    new_thumbnail = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PNG, b"new-thumbnail", max_bytes=100
    )
    new_revision.thumbnail = FileObject(
        backend="documents", filename=new_thumbnail.key, content_type="image/png"
    )
    db.add(new_revision)
    await db.commit()
    new_revision_id = new_revision.id
    new_object = local_object_path(key)
    thumbnail_url = f"{workspace_base}/items/{item_id}/thumbnail"
    index = search_index(db)
    await index.index_revision(db, new_revision.id)
    recommendation = await request_item_tag_recommendation(
        db,
        item_id,
        workspace_id=item.workspace_id,
        actor_id=item.created_by,
    )
    previous_generation = recommendation.generation_token
    await db.commit()

    try:
        assert (await client.get(thumbnail_url)).content == b"new-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == [item_id]

        deleted = await client.delete(
            f"{workspace_base}/items/{item_id}/revisions/{new_revision_id}"
        )

        assert deleted.status_code == 200
        assert await db.get(FileRevision, new_revision_id) is None
        await document_workflows.delete_unreferenced_objects_step(
            item.created_by,
            item.workspace_id,
            [key, new_thumbnail.key],
        )
        assert not new_object.exists()
        assert not local_object_path(new_thumbnail.key).exists()
        assert (await client.get(thumbnail_url)).content == b"old-thumbnail"
        assert await index.search(db, "deletedsearchtoken") == []
        refreshed = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
        )
        assert refreshed is not None
        assert refreshed.generation_token == previous_generation
        assert refreshed.generated_at is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"\x89PNG\r\n\x1a\ngraphical", id="valid-image"),
        pytest.param(b"not really a png", id="invalid-image-bytes"),
        pytest.param(b"", id="empty-image"),
    ],
)
async def test_graphical_abstract_upload_admits_worker_without_creating_attachment(
    async_db, async_session_factory, tmp_path, monkeypatch, fake_durable_operations, content
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"

    try:
        uploaded = await client.post(
            f"{workspace_base}/items/{item_id}/attachments",
            data={"graphical_abstract": "true"},
            files={"attachment": ("abstract.png", content, "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 202
        workflow_id = uploaded.json()["id"]
        assert workflow_id.startswith("upload-attachment:")
        enqueue = fake_durable_operations.enqueues[-1]
        assert enqueue["workflow_id"] == workflow_id
        assert enqueue["workflow_name"] == document_workflows.ATTACHMENT_UPLOAD_WORKFLOW
        assert enqueue["queue_name"] == "documents.upload"
        assert enqueue["attributes"]["operation"] == "upload_attachment"
        message_workflow_id, receipt, topic, _idempotency_key = fake_durable_operations.messages[-1]
        assert message_workflow_id == workflow_id
        assert topic == "upload-complete"
        assert receipt["status"] == "complete"
        assert receipt["size"] == len(content)
        assert enqueue["attributes"]["object_key"] == receipt["key"]
        assert await db.scalar(select(Attachment).where(Attachment.item_id == item_id)) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_uploaded_graphical_abstract_is_served_as_item_thumbnail(
    async_db, async_session_factory, tmp_path, monkeypatch, fake_durable_operations
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    workspace_id = item.workspace_id
    workspace_base = f"/api/v1/workspaces/{workspace_id}"
    image = b"\x89PNG\r\n\x1a\ngraphical"

    try:
        uploaded = await client.post(
            f"{workspace_base}/items/{item_id}/attachments",
            data={"graphical_abstract": "true"},
            files={"attachment": ("abstract.png", image, "image/png")},
            follow_redirects=False,
        )

        assert uploaded.status_code == 202
        workflow_id = uploaded.json()["id"]
        assert await db.scalar(select(Attachment.id).where(Attachment.item_id == item_id)) is None
        message_workflow_id, receipt, topic, _idempotency_key = fake_durable_operations.messages[-1]
        assert message_workflow_id == workflow_id
        assert topic == "upload-complete"

        async def receive(received_topic, *, timeout_seconds):
            await asyncio.sleep(0)
            assert received_topic == "upload-complete"
            assert timeout_seconds > 0
            return receipt

        monkeypatch.setattr(document_workflows, "DBOS", SimpleNamespace(recv_async=receive))
        worker_body = document_workflows.upload_attachment_workflow.__wrapped__.__wrapped__
        enqueue = fake_durable_operations.enqueues[-1]
        attachment_id = enqueue["args"][3]
        result = await worker_body(*enqueue["args"])

        assert result == {"attachment_id": attachment_id, "item_id": item_id}
        saved = await db.get(Attachment, attachment_id)
        assert saved is not None
        assert saved.role is AttachmentRole.graphical_abstract
        assert saved.file.content_type == "image/png"

        thumbnail = await client.get(f"{workspace_base}/items/{item_id}/thumbnail")

        assert thumbnail.status_code == 200
        assert thumbnail.headers["content-type"] == "image/png"
        assert thumbnail.content == image
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_regular_attachment_accepts_non_image_content(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id

    try:
        uploaded = await client.post(
            f"{workspace_base}/items/{item_id}/attachments",
            files={"attachment": ("dataset.csv", b"column\nvalue\n", "text/csv")},
            follow_redirects=False,
        )
        assert uploaded.status_code == 202
        assert uploaded.json()["id"].startswith("upload-attachment:")
        assert await db.scalar(select(Attachment).where(Attachment.item_id == item_id)) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_update_detects_conflicts_and_updates_search(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        updated = await client.put(
            f"{workspace_base}/items/{item.id}",
            json=json_payload({
                "expected_version": 1,
                "metadata": {"title": "Revised Paper", "abstract": "Quantum transport"},
            }),
        )
        assert updated.status_code == 200
        await db.refresh(item)
        assert item.version == 2
        assert item.title == "Revised Paper"

        results = await client.get(f"{workspace_base}/items", params={"query": "quantum"})
        assert results.status_code == 200
        assert results.json()["items"][0]["title_html"] == "Revised Paper"

        stale = await client.put(
            f"{workspace_base}/items/{item.id}",
            json=json_payload({"expected_version": 1, "metadata": {"title": "Lost update"}}),
        )
        assert stale.status_code == 409
        await db.refresh(item)
        assert item.title == "Revised Paper"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_update_uses_atomic_optimistic_lock(async_db, async_session_factory):
    db = async_db
    owner = User(username="concurrent_owner", password_hash="unused")
    db.add(owner)
    await db.flush()
    await provision_initial_workspace(db, owner)
    item = Item(
        workspace_id=fixture_workspace_id(owner),
        title="Original",
        created_by=owner.id,
    )
    db.add(item)
    await db.commit()
    owner_id = owner.id
    item_id = item.id

    async with (
        async_session_factory() as first,
        async_session_factory() as second,
    ):
        first_owner = await first.get(User, owner_id)
        second_owner = await second.get(User, owner_id)
        first_item = await first.get(Item, item_id)
        second_item = await second.get(Item, item_id)
        assert first_owner and second_owner and first_item and second_item
        assert first_item.version == second_item.version == 1

        await revise_item_metadata(
            first,
            first_owner,
            fixture_workspace_id(owner),
            item_id,
            first_item.version,
            ItemMetadata(title="First update"),
        )
        with pytest.raises(VersionConflict):
            await revise_item_metadata(
                second,
                second_owner,
                fixture_workspace_id(owner),
                item_id,
                second_item.version,
                ItemMetadata(title="Lost update"),
            )
    db.expire_all()
    refreshed = await db.get(Item, item_id)
    assert refreshed is not None
    assert refreshed.title == "First update"


@pytest.mark.anyio
async def test_content_media_types_at_runtime(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    store = get_object_store()

    try:
        # 1. Attachment downloads retain their stored media type.
        att_key = "attachments/test.pdf"
        await store.put(att_key, b"%PDF-1.4 test")
        attachment = Attachment(
            id=str(uuid4()),
            workspace_id=item.workspace_id,
            item_id=item_id,
            file=FileObject(
                backend="documents",
                filename=att_key,
                size=13,
                content_type="application/pdf",
                metadata={"original_name": "test.pdf"},
            ),
            role=None,
            created_by=item.created_by,
        )
        db.add(attachment)
        await db.flush()

        att_resp = await client.get(
            f"{workspace_base}/items/{item_id}/attachments/{attachment.id}/content"
        )
        assert att_resp.status_code == 200
        assert att_resp.headers["content-type"] == "application/pdf"
        assert 'filename="test.pdf"' in att_resp.headers["content-disposition"]

        # 2. Citation text returns text/plain or text/html based on output param
        cite_text = await client.get(
            f"{workspace_base}/items/{item_id}/citation/content?output=text"
        )
        assert cite_text.status_code == 200
        assert "text/plain" in cite_text.headers["content-type"]

        cite_html = await client.get(
            f"{workspace_base}/items/{item_id}/citation/content?output=html"
        )
        assert cite_html.status_code == 200
        assert "text/html" in cite_html.headers["content-type"]

        # 3. Bibliography returns application/x-bibtex or application/x-research-info-systems
        bib_resp = await client.get(
            f"{workspace_base}/items/{item_id}/bibliography?file_format=bibtex"
        )
        assert bib_resp.status_code == 200
        assert "application/x-bibtex" in bib_resp.headers["content-type"]

        ris_resp = await client.get(
            f"{workspace_base}/items/{item_id}/bibliography?file_format=ris"
        )
        assert ris_resp.status_code == 200
        assert "application/x-research-info-systems" in ris_resp.headers["content-type"]

        # 4. Graphical abstract thumbnail returns its image media type (e.g. image/jpeg)
        ga_key = "attachments/ga.jpg"
        await store.put(ga_key, b"\xff\xd8\xff test")
        ga_attachment = Attachment(
            id=str(uuid4()),
            workspace_id=item.workspace_id,
            item_id=item_id,
            file=FileObject(
                backend="documents",
                filename=ga_key,
                size=11,
                content_type="image/jpeg",
                metadata={"original_name": "abstract.jpg"},
            ),
            role=AttachmentRole.graphical_abstract,
            created_by=item.created_by,
        )
        db.add(ga_attachment)
        await db.flush()

        thumb_resp = await client.get(f"{workspace_base}/items/{item_id}/thumbnail")
        assert thumb_resp.status_code == 200
        assert thumb_resp.headers["content-type"] == "image/jpeg"
    finally:
        await client.aclose()
        get_settings.cache_clear()
