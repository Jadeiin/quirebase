from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx2
import pytest
from app_helpers import create_web_test_app
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.accounts import create_api_token
from quirebase.core.database import get_db
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    AuditEvent,
    FileRevision,
    Item,
    ItemTag,
    PdfAnnotation,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    SystemRole,
    User,
    WorkspaceMember,
    WorkspaceRole,
)


@asynccontextmanager
async def api_client(factory):
    app = create_web_test_app(mcp_session_factory=factory)

    async def override_db():
        session = factory()
        try:
            yield session
        finally:
            await session.close()

    app.dependency_overrides[get_db] = override_db
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client, app


def bearer(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


@pytest.mark.anyio
async def test_http_api_requires_a_bearer_api_token_and_rejects_cookie_or_query_token(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="api-auth-user", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    workspace_id = fixture_workspace_id(user)
    await db.commit()
    grant = await create_api_token(db, user, "HTTP API", expires_in_days=30)

    async with api_client(async_session_factory) as (client, _app):
        client.cookies.set("quirebase_session", "not-an-api-credential")
        base = f"/api/v1/workspaces/{workspace_id}"
        missing = await client.get(f"{base}/items")
        query = await client.get(f"{base}/items?token={grant.raw_token}")
        invalid = await client.get(f"{base}/items", headers=bearer("invalid"))
        accepted = await client.get(f"{base}/items", headers=bearer(grant.raw_token))

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert query.status_code == 401
    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"items": [], "total": 0, "page": 1, "per_page": 25}


@pytest.mark.anyio
async def test_http_api_includes_the_public_capability_set(
    async_session_factory,
):
    expected = {
        ("GET", "/api/v1/workspaces/{workspace_id}/items"),
        ("POST", "/api/v1/workspaces/{workspace_id}/items"),
        ("GET", "/api/v1/workspaces/{workspace_id}/items/{item_id}"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/items/{item_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/projects"),
        ("POST", "/api/v1/workspaces/{workspace_id}/projects"),
        ("GET", "/api/v1/workspaces/{workspace_id}/projects/{project_id}"),
        ("PATCH", "/api/v1/workspaces/{workspace_id}/projects/{project_id}"),
        ("POST", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/archive"),
        ("POST", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/restore"),
        ("POST", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/visibility"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/members"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/members/{user_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/items/{item_id}/documents"),
        ("GET", "/api/v1/workspaces/{workspace_id}/items/{item_id}/annotations"),
        ("POST", "/api/v1/workspaces/{workspace_id}/items/{item_id}/annotations"),
        ("PATCH", "/api/v1/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}"),
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/items/{item_id}/annotations/{annotation_id}/replies",
        ),
        ("GET", "/api/v1/workspaces/{workspace_id}/tags"),
        ("POST", "/api/v1/workspaces/{workspace_id}/items/{item_id}/tags"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/items/{item_id}/tags/{tag_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/items/{item_id}/discussions"),
        ("POST", "/api/v1/workspaces/{workspace_id}/items/{item_id}/discussions"),
        ("POST", "/api/v1/workspaces/{workspace_id}/discovery/search"),
    }

    async with api_client(async_session_factory) as (_client, app):
        paths = app.openapi()["paths"]
        actual = {
            (method.upper(), path)
            for path, methods in paths.items()
            for method in methods
            if method in {"get", "post", "put", "patch", "delete"}
        }

    # The unified router also owns browser session and UI-specific aggregate capabilities.
    assert expected <= actual
    assert paths["/api/v1/workspaces/{workspace_id}/items"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/LibrarySearchView"}
    assert paths["/api/v1/workspaces/{workspace_id}/items/{item_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"] == {"$ref": "#/components/schemas/ItemDetailView"}
    assert paths["/api/v1/workspaces/{workspace_id}/projects/{project_id}"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ProjectDetailView"}
    assert paths["/api/v1/workspaces/{workspace_id}/items/{item_id}/documents"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/DocumentListView"}


@pytest.mark.anyio
async def test_http_api_library_project_tag_and_discussion_lifecycle(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="api-lifecycle", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    workspace_base = f"/api/v1/workspaces/{fixture_workspace_id(user)}"
    await db.commit()
    grant = await create_api_token(db, user, "Lifecycle", expires_in_days=30)
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        created = await client.post(
            f"{workspace_base}/items",
            headers=headers,
            json={
                "title": "HTTP API Item",
                "abstract": "Shared contract",
                "authors": [{"last_name": "Li", "first_name": "Ming"}],
                "custom_fields": [{"name": "rating", "value": 5}],
            },
        )
        assert created.status_code == 201
        item_id = created.json()["id"]
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "item.create", AuditEvent.target_id == item_id
            )
        )
        assert event is not None
        assert json.loads(event.detail) == {
            "invocation": {
                "protocol": "http",
                "operation": "create_library_item",
                "api_token_id": grant.token_id,
                "client_id": "http-api",
            }
        }

        listed = await client.get(f"{workspace_base}/items?query=HTTP", headers=headers)
        detail = await client.get(f"{workspace_base}/items/{item_id}", headers=headers)
        assert listed.json()["items"][0]["id"] == item_id
        assert detail.json()["metadata"]["custom_fields"] == [{"name": "rating", "value": 5}]

        metadata = detail.json()["metadata"]
        metadata["title"] = "Updated through HTTP API"
        updated = await client.put(
            f"{workspace_base}/items/{item_id}",
            headers=headers,
            json={"expected_version": detail.json()["version"], "metadata": metadata},
        )
        assert updated.status_code == 200

        project = await client.post(
            f"{workspace_base}/projects", headers=headers, json={"name": "API Project"}
        )
        project_id = project.json()["id"]
        assert (
            await client.put(
                f"{workspace_base}/projects/{project_id}/items/{item_id}", headers=headers
            )
        ).json() == {"ok": True}
        assert (
            await client.get(f"{workspace_base}/projects/{project_id}", headers=headers)
        ).json()["item_count"] == 1

        tag = await client.post(
            f"{workspace_base}/items/{item_id}/tags", headers=headers, json={"name": "Reviewed"}
        )
        assert tag.status_code == 200
        assert (await client.get(f"{workspace_base}/tags", headers=headers)).json()[0][
            "name"
        ] == "Reviewed"
        cleared = await client.put(
            f"{workspace_base}/items/{item_id}/tags",
            headers=headers,
            json={"add_tag_ids": [], "remove_tag_ids": [tag.json()["id"]], "new_names": []},
        )
        assert cleared.status_code == 200
        assert await db.get(ItemTag, (item_id, tag.json()["id"])) is None

        discussion = await client.post(
            f"{workspace_base}/items/{item_id}/discussions",
            headers=headers,
            json={"body": "Programmatic note"},
        )
        assert discussion.status_code == 201
        message_id = discussion.json()["id"]
        assert (
            await client.get(f"{workspace_base}/items/{item_id}/discussions", headers=headers)
        ).json()[0]["body"] == "Programmatic note"
        assert (
            await client.delete(
                f"{workspace_base}/items/{item_id}/discussions/{message_id}", headers=headers
            )
        ).json() == {"ok": True}


@pytest.mark.anyio
async def test_http_api_document_and_annotation_views_match_api_contracts(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="api-annotations", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    workspace_base = f"/api/v1/workspaces/{fixture_workspace_id(user)}"
    item_response_title = "Annotated Item"
    await db.commit()
    user_id = user.id
    grant = await create_api_token(db, user, "Annotations", expires_in_days=30)
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        item_id = (
            await client.post(
                f"{workspace_base}/items", headers=headers, json={"title": item_response_title}
            )
        ).json()["id"]

    project = Project(
        workspace_id=fixture_workspace_id(user),
        name="Annotation project",
        created_by=user_id,
    )
    db.add(project)
    await db.flush()
    db.add(
        ProjectItem(
            workspace_id=fixture_workspace_id(user),
            project_id=project.id,
            item_id=item_id,
            added_by=user_id,
        )
    )
    revision = FileRevision(
        workspace_id=fixture_workspace_id(user),
        item_id=item_id,
        object_key="objects/api.pdf",
        size=100,
        mime_type="application/pdf",
        original_name="api.pdf",
        page_count=1,
        page_geometry="[[0, 0, 100, 100]]",
        processing_state="ready",
        created_by=user_id,
    )
    db.add(revision)
    await db.commit()

    async with api_client(async_session_factory) as (client, _app):
        documents = await client.get(f"{workspace_base}/items/{item_id}/documents", headers=headers)
        assert documents.status_code == 200
        assert documents.json()["files"][0]["original_name"] == "api.pdf"

        created = await client.post(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "project",
                "project_id": project.id,
                "body": "API annotation",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
                },
            },
        )
        assert created.status_code == 201
        annotation = created.json()
        annotation_id = annotation["id"]
        assert annotation["payload"]["type"] == "note"
        assert annotation["author_display_name"] == user.username
        assert annotation["mine"] is True and annotation["editable"] is True
        root_id_as_reply = await client.post(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies",
            headers=headers,
            json={"id": annotation_id, "body": "Conflicting reply ID"},
        )
        assert root_id_as_reply.status_code == 409
        reply_id = str(uuid4())
        created_reply = await client.post(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies",
            headers=headers,
            json={"id": reply_id, "body": "API reply"},
        )
        assert created_reply.status_code == 201
        assert created_reply.json()["body"] == "API reply"
        reply_id_as_root = await client.post(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": reply_id,
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "project",
                "project_id": project.id,
                "body": "Conflicting annotation ID",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
                },
            },
        )
        assert reply_id_as_root.status_code == 409
        listed = await client.get(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            params={"revision_id": revision.id, "project_id": project.id},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == annotation_id
        assert listed.json()[0]["replies"][0]["id"] == reply_id
        review = await client.get(
            f"{workspace_base}/items/{item_id}/annotations/review",
            headers=headers,
        )
        assert review.status_code == 200
        assert review.json()["revisions"] == [{"id": revision.id, "original_name": "api.pdf"}]
        assert review.json()["annotations"][0]["id"] == annotation_id
        assert review.json()["annotations"][0]["revision_name"] == "api.pdf"
        assert review.json()["annotations"][0]["replies"][0]["id"] == reply_id
        updated_reply = await client.patch(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
            headers=headers,
            json={"version": 1, "body": "Updated API reply"},
        )
        assert updated_reply.status_code == 200
        assert updated_reply.json()["version"] == 2
        updated = await client.patch(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            json={
                "version": annotation["version"],
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": "Updated API annotation",
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["body"] == "Updated API annotation"
        assert updated.json()["version"] == 2
        assert updated.json()["replies"][0]["id"] == reply_id
        assert updated.json()["replies"][0]["body"] == "Updated API reply"
        deleted_reply = await client.delete(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
            headers=headers,
            params={"version": 2},
        )
        assert deleted_reply.status_code == 200
        deleted_reply_id_as_root = await client.post(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": reply_id,
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "scope": "project",
                "project_id": project.id,
                "body": "Still conflicting after soft deletion",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
                },
            },
        )
        assert deleted_reply_id_as_root.status_code == 409
        conflict = await client.delete(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            params={"version": 1},
        )
        assert conflict.status_code == 409
        deleted = await client.delete(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            params={"version": 2},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        assert (
            await client.get(
                f"{workspace_base}/items/{item_id}/annotations",
                headers=headers,
                params={"revision_id": revision.id},
            )
        ).json() == []


@pytest.mark.anyio
async def test_workspace_admin_moderates_other_users_project_annotations_via_http_api(
    async_db, async_session_factory
):
    db = async_db
    author = User(username="api-annotation-author", password_hash="unused")
    administrator = User(
        username="api-annotation-administrator",
        password_hash="unused",
        role=SystemRole.administrator,
    )
    db.add_all([author, administrator])
    await db.flush()
    await provision_initial_workspace(db, author)
    workspace_id = fixture_workspace_id(author)
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=administrator.id,
            role=WorkspaceRole.admin,
            invited_by=author.id,
        )
    )
    item = Item(
        workspace_id=workspace_id,
        title="Administrator annotation access",
        created_by=author.id,
    )
    project = Project(
        workspace_id=workspace_id,
        name="Unjoined annotation project",
        created_by=author.id,
        visibility=ProjectVisibility.managed,
    )
    archived_project = Project(
        workspace_id=workspace_id,
        name="Archived annotation project",
        created_by=author.id,
        visibility=ProjectVisibility.managed,
        state=ProjectState.archived,
    )
    db.add_all([item, project, archived_project])
    await db.flush()
    project_item = ProjectItem(
        workspace_id=workspace_id,
        project_id=project.id,
        item_id=item.id,
        added_by=author.id,
    )
    archived_project_item = ProjectItem(
        workspace_id=workspace_id,
        project_id=archived_project.id,
        item_id=item.id,
        added_by=author.id,
    )
    archived_project_member = ProjectMember(
        workspace_id=workspace_id,
        project_id=archived_project.id,
        user_id=administrator.id,
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key="objects/admin-annotations.pdf",
        size=100,
        mime_type="application/pdf",
        original_name="admin-annotations.pdf",
        page_count=1,
        page_geometry="[[0, 0, 100, 100]]",
        processing_state="ready",
        created_by=author.id,
    )
    db.add_all([revision, project_item, archived_project_item, archived_project_member])
    await db.flush()
    payload = {
        "type": "note",
        "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
    }
    annotations = [
        PdfAnnotation(
            workspace_id=workspace_id,
            file_revision_id=revision.id,
            item_id=item.id,
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_item_id=project_item.id,
            payload=payload,
        ),
        PdfAnnotation(
            workspace_id=workspace_id,
            file_revision_id=revision.id,
            item_id=item.id,
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_item_id=project_item.id,
            payload=payload,
        ),
    ]
    archived_annotation = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=archived_project_item.id,
        payload=payload,
    )
    db.add_all([*annotations, archived_annotation])
    await db.commit()
    grant = await create_api_token(
        db, administrator, "Administrator annotations", expires_in_days=30
    )
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        review = await client.get(
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/review",
            headers=headers,
        )
        assert review.status_code == 200
        reviewed = {entry["id"]: entry for entry in review.json()["annotations"]}
        assert set(reviewed) == {annotation.id for annotation in annotations} | {
            archived_annotation.id
        }
        assert review.json()["total"] == 3
        assert set(reviewed[archived_annotation.id]["allowed_actions"]) == set()
        assert set(reviewed[annotations[0].id]["allowed_actions"]) >= {"hide", "archive", "lock"}
        assert review.json()["page"] == 1
        assert review.json()["per_page"] == 50
        paged_reviews = [
            await client.get(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/review",
                headers=headers,
                params={"page": page, "per_page": 1},
            )
            for page in (1, 2, 3)
        ]
        assert all(response.status_code == 200 for response in paged_reviews)
        assert {response.json()["annotations"][0]["id"] for response in paged_reviews} == set(
            reviewed
        )
        assert all(response.json()["total"] == 3 for response in paged_reviews)
        assert all(
            set(response.json()["annotations"][0]["allowed_actions"]) >= {"hide", "archive", "lock"}
            for response in paged_reviews
            if response.json()["annotations"][0]["id"] != archived_annotation.id
        )

        for annotation, action in zip(annotations, ("hide", "archive"), strict=True):
            moderated = await client.post(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/"
                f"{annotation.id}/moderation",
                headers=headers,
                json={"action": action, "version": 1},
            )
            assert moderated.status_code == 200
            assert moderated.json()["body"] is None
            assert moderated.json()["version"] == 2
            assert moderated.json()["moderated_by"] == administrator.id


@pytest.mark.anyio
async def test_project_participation_does_not_gate_workspace_project_access(
    async_db, async_session_factory
):
    db = async_db
    owner = User(username="project-governance-owner", password_hash="unused")
    administrator = User(username="project-governance-admin", password_hash="unused")
    db.add_all([owner, administrator])
    await db.flush()
    await provision_initial_workspace(db, owner)
    workspace_id = fixture_workspace_id(owner)
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=administrator.id,
            role=WorkspaceRole.admin,
            invited_by=owner.id,
        )
    )
    active = Project(
        workspace_id=workspace_id,
        name="Managed active Project",
        created_by=owner.id,
        visibility=ProjectVisibility.managed,
    )
    archived = Project(
        workspace_id=workspace_id,
        name="Managed archived Project",
        created_by=owner.id,
        visibility=ProjectVisibility.managed,
        state=ProjectState.archived,
    )
    workspace_visible = Project(
        workspace_id=workspace_id,
        name="Workspace-visible Project",
        created_by=owner.id,
        visibility=ProjectVisibility.workspace,
    )
    db.add_all([active, archived, workspace_visible])
    await db.commit()
    grant = await create_api_token(db, administrator, "Project governance", expires_in_days=30)
    headers = bearer(grant.raw_token)
    base = f"/api/v1/workspaces/{workspace_id}/projects"

    async with api_client(async_session_factory) as (client, _app):
        projects = await client.get(base, headers=headers)
        assert projects.status_code == 200
        summaries = {project["id"]: project for project in projects.json()}
        active_actions = set(summaries[active.id]["allowed_actions"])
        archived_actions = set(summaries[archived.id]["allowed_actions"])
        assert summaries[active.id]["is_member"] is False
        assert "members.manage" in active_actions
        assert "settings" in active_actions
        assert "archive" in active_actions
        assert "restore" in archived_actions
        assert "members.manage" not in archived_actions
        assert "settings" not in archived_actions

        active_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert active_detail.status_code == 200
        assert active_detail.json()["members"] == []
        assert active_detail.json()["allowed_actions"] == summaries[active.id]["allowed_actions"]

        workspace_summary = next(
            row for row in projects.json() if row["id"] == workspace_visible.id
        )
        assert workspace_summary["is_member"] is True
        assert "members.manage" not in workspace_summary["allowed_actions"]
        workspace_detail = await client.get(f"{base}/{workspace_visible.id}", headers=headers)
        assert workspace_detail.json()["members"] == []
        add_workspace_member = await client.put(
            f"{base}/{workspace_visible.id}/members",
            headers=headers,
            json={"username": administrator.username},
        )
        remove_workspace_member = await client.delete(
            f"{base}/{workspace_visible.id}/members/{administrator.id}", headers=headers
        )
        assert add_workspace_member.status_code == 409
        assert add_workspace_member.json()["code"] == "project_member_conflict"
        assert remove_workspace_member.status_code == 409
        assert remove_workspace_member.json()["code"] == "project_member_conflict"

        settings = await client.patch(
            f"{base}/{active.id}",
            headers=headers,
            json={"name": "Still accessible", "description": "", "visibility": "open"},
        )
        assert settings.status_code == 200
        join = await client.post(f"{base}/{active.id}/join", headers=headers)
        assert join.status_code == 200
        project_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert project_detail.status_code == 200
        assert project_detail.json()["is_member"] is True
        leave = await client.post(f"{base}/{active.id}/leave", headers=headers)
        assert leave.status_code == 200
        project_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert project_detail.status_code == 200
        assert project_detail.json()["is_member"] is False

        managed_settings = await client.patch(
            f"{base}/{active.id}",
            headers=headers,
            json={"name": "Still accessible", "description": "", "visibility": "managed"},
        )
        assert managed_settings.status_code == 200
        participant = await client.put(
            f"{base}/{active.id}/members",
            headers=headers,
            json={"username": owner.username},
        )
        assert participant.status_code == 200
