from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import httpx2
import pytest
from advanced_alchemy.types import FileObject
from app_helpers import create_web_test_app, json_payload
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
    ProjectParticipation,
    ProjectState,
    SystemRole,
    Tag,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.workspaces import archive_workspace, freeze_workspace_governance


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
async def test_project_creation_requires_an_explicit_participation_choice(
    async_db, async_session_factory
):
    actor = User(username="explicit-project-mode", password_hash="unused")
    other = User(username="other-project-user", password_hash="unused")
    async_db.add_all([actor, other])
    await async_db.flush()
    workspace = await provision_initial_workspace(async_db, actor)
    async_db.add(WorkspaceMember(workspace_id=workspace.id, user_id=other.id, role="editor"))
    await async_db.commit()
    grant = await create_api_token(async_db, actor, "Project mode", expires_in_days=30)
    headers = bearer(grant.raw_token)
    endpoint = f"/api/v1/workspaces/{workspace.id}/projects"

    async with api_client(async_session_factory) as (client, _app):
        rejected = await client.post(endpoint, headers=headers, json={"name": "Unspecified"})
        assert rejected.status_code == 422
        async with async_session_factory() as observer:
            assert await observer.scalar(select(Project.id)) is None
            assert (
                await observer.scalar(
                    select(AuditEvent.id).where(AuditEvent.action == "project.create")
                )
                is None
            )
        created = await client.post(
            endpoint, headers=headers, json={"name": "Open project", "participation": "open"}
        )
        assert created.status_code == 201
        detail = await client.get(f"{endpoint}/{created.json()['id']}", headers=headers)
        assert detail.status_code == 200 and detail.json()["participation"] == "open"
        async with async_session_factory() as observer:
            participants = list(await observer.scalars(select(ProjectMember.user_id)))
            assert participants == [actor.id]


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
    assert accepted.json() == {"items": [], "total": 0, "limit": 25, "offset": 0}


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
        ("PUT", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/items/{item_id}"),
        ("POST", "/api/v1/workspaces/{workspace_id}/projects/{project_id}/participants"),
        (
            "DELETE",
            "/api/v1/workspaces/{workspace_id}/projects/{project_id}/participants/{user_id}",
        ),
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

    assert app.openapi()["components"]["schemas"]["AdminUsersView"]["properties"]["items"][
        "items"
    ] == {"$ref": "#/components/schemas/AdminUserView"}

    # The unified router also owns browser session and UI-specific aggregate capabilities.
    assert expected <= actual
    assert paths["/api/v1/workspaces/{workspace_id}/items"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/OffsetPagination_ItemSearchView_"}
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
            json=json_payload({
                "title": "HTTP API Item",
                "abstract": "Shared contract",
                "authors": [{"last_name": "Li", "first_name": "Ming"}],
                "custom_fields": [{"name": "rating", "value": 5}],
            }),
        )
        assert created.status_code == 201
        item_id = created.json()["id"]
        event = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "item.create", AuditEvent.target_id == str(item_id)
            )
        )
        assert event is not None
        assert event.detail == json_payload({
            "invocation": {
                "protocol": "http",
                "operation": "create_library_item",
                "api_token_id": grant.token_id,
                "client_id": "http-api",
            }
        })

        listed = await client.get(f"{workspace_base}/items?query=HTTP", headers=headers)
        detail = await client.get(f"{workspace_base}/items/{item_id}", headers=headers)
        assert listed.json()["items"][0]["id"] == item_id
        assert detail.json()["metadata"]["custom_fields"] == [{"name": "rating", "value": 5}]

        metadata = detail.json()["metadata"]
        metadata["title"] = "Updated through HTTP API"
        updated = await client.put(
            f"{workspace_base}/items/{item_id}",
            headers=headers,
            json=json_payload({"expected_version": detail.json()["version"], "metadata": metadata}),
        )
        assert updated.status_code == 200

        project = await client.post(
            f"{workspace_base}/projects",
            headers=headers,
            json=json_payload({"name": "API Project", "participation": "workspace"}),
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
            f"{workspace_base}/items/{item_id}/tags",
            headers=headers,
            json=json_payload({"name": "Reviewed"}),
        )
        assert tag.status_code == 200
        assert (await client.get(f"{workspace_base}/tags", headers=headers)).json()[0][
            "name"
        ] == "Reviewed"
        cleared = await client.put(
            f"{workspace_base}/items/{item_id}/tags",
            headers=headers,
            json=json_payload({
                "add_tag_ids": [],
                "remove_tag_ids": [tag.json()["id"]],
                "new_names": [],
            }),
        )
        assert cleared.status_code == 200
        assert await db.get(ItemTag, (item_id, tag.json()["id"])) is None

        discussion = await client.post(
            f"{workspace_base}/items/{item_id}/discussions",
            headers=headers,
            json=json_payload({"body": "Programmatic note"}),
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
                f"{workspace_base}/items",
                headers=headers,
                json=json_payload({"title": item_response_title}),
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
        page_count=1,
        page_geometry=[[0, 0, 100, 100]],
        processing_state="ready",
        created_by=user_id,
        file=FileObject(
            backend="documents",
            filename="objects/api.pdf",
            size=100,
            content_type="application/pdf",
            metadata={"original_name": "api.pdf"},
        ),
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
            json=json_payload({
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
            }),
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
            json=json_payload({"id": annotation_id, "body": "Conflicting reply ID"}),
        )
        assert root_id_as_reply.status_code == 409
        reply_id = str(uuid4())
        created_reply = await client.post(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies",
            headers=headers,
            json=json_payload({"id": reply_id, "body": "API reply"}),
        )
        assert created_reply.status_code == 201
        assert created_reply.json()["body"] == "API reply"
        reply_id_as_root = await client.post(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            json=json_payload({
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
            }),
        )
        assert reply_id_as_root.status_code == 409
        listed = await client.get(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
            params={"revision_id": revision.id, "project_id": project.id},
        )
        assert listed.status_code == 200
        assert listed.json()["annotations"][0]["id"] == annotation_id
        assert listed.json()["annotations"][0]["replies"][0]["id"] == reply_id
        review = await client.get(
            f"{workspace_base}/items/{item_id}/annotations",
            headers=headers,
        )
        assert review.status_code == 200
        assert review.json()["revisions"] == json_payload([
            {"id": revision.id, "original_name": "api.pdf"}
        ])
        assert review.json()["annotations"][0]["id"] == annotation_id
        assert review.json()["annotations"][0]["revision_name"] == "api.pdf"
        assert review.json()["annotations"][0]["replies"][0]["id"] == reply_id
        updated_reply = await client.patch(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
            headers=headers,
            json=json_payload({"version": 1, "body": "Updated API reply"}),
        )
        assert updated_reply.status_code == 200
        assert updated_reply.json()["version"] == 2
        updated = await client.patch(
            f"{workspace_base}/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            json=json_payload({
                "version": annotation["version"],
                "page_index": annotation["page_index"],
                "kind": annotation["kind"],
                "scope": annotation["scope"],
                "project_id": annotation["project_id"],
                "body": "Updated API annotation",
                "selected_text": annotation["selected_text"],
                "payload": annotation["payload"],
            }),
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
            json=json_payload({
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
            }),
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
        ).json()["annotations"] == []


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
        participation=ProjectParticipation.managed,
    )
    archived_project = Project(
        workspace_id=workspace_id,
        name="Archived annotation project",
        created_by=author.id,
        participation=ProjectParticipation.managed,
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
        page_count=1,
        page_geometry=[[0, 0, 100, 100]],
        processing_state="ready",
        created_by=author.id,
        file=FileObject(
            backend="documents",
            filename="objects/admin-annotations.pdf",
            size=100,
            content_type="application/pdf",
            metadata={"original_name": "admin-annotations.pdf"},
        ),
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
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
            headers=headers,
        )
        assert review.status_code == 200
        reviewed = {entry["id"]: entry for entry in review.json()["annotations"]}
        assert set(reviewed) == set(
            map(str, {annotation.id for annotation in annotations} | {archived_annotation.id})
        )
        assert review.json()["total"] == 3
        assert set(reviewed[str(archived_annotation.id)]["authorization"]["allowed"]) == set()
        assert set(reviewed[str(annotations[0].id)]["authorization"]["allowed"]) == {
            "project_annotation.hide",
            "project_annotation.archive",
            "project_annotation.lock",
            "project_annotation.delete",
        }
        assert review.json()["page"] == 1
        assert review.json()["per_page"] == 50

        sources = await client.get(
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
            headers=headers,
            params=[
                ("revision_id", revision.id),
                ("scope", "project"),
                ("project_id", project.id),
                ("project_id", archived_project.id),
            ],
        )
        assert sources.status_code == 200
        assert sources.json()["total"] == 3
        assert {entry["project_name"] for entry in sources.json()["annotations"]} == {
            project.name,
            archived_project.name,
        }
        assert {entry["id"] for entry in sources.json()["projects"]} == {
            str(project.id),
            str(archived_project.id),
        }
        cursor_ids = []
        cursor = None
        for _ in range(3):
            query = {"pagination": "cursor", "per_page": 1}
            if cursor is not None:
                query["cursor"] = cursor
            response = await client.get(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
                headers=headers,
                params=query,
            )
            assert response.status_code == 200
            cursor_ids.append(response.json()["annotations"][0]["id"])
            cursor = response.json()["next_cursor"]
        assert cursor_ids == sorted(reviewed)
        assert cursor is None
        for query, expected in (
            ({"pagination": "unknown"}, 422),
            ({"pagination": "cursor", "page": 2}, 422),
            ({"cursor": annotations[0].id}, 422),
            ({"project_id": uuid4()}, 404),
            ({"revision_id": uuid4()}, 404),
            ({"page": 0}, 422),
            ({"per_page": 101}, 422),
            ({"scope": "unknown"}, 422),
        ):
            response = await client.get(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
                headers=headers,
                params=query,
            )
            assert response.status_code == expected
        removed = await client.get(
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/review",
            headers=headers,
        )
        assert removed.status_code == 404
        paged_reviews = [
            await client.get(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
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
            set(response.json()["annotations"][0]["authorization"]["allowed"])
            == {
                "project_annotation.hide",
                "project_annotation.archive",
                "project_annotation.lock",
                "project_annotation.delete",
            }
            for response in paged_reviews
            if response.json()["annotations"][0]["id"] != str(archived_annotation.id)
        )

        for annotation, action in zip(annotations, ("hide", "archive"), strict=True):
            moderated = await client.post(
                f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/"
                f"{annotation.id}/moderation",
                headers=headers,
                json=json_payload({"action": action, "version": 1}),
            )
            assert moderated.status_code == 200
            assert moderated.json()["body"] is None
            assert moderated.json()["version"] == 2
            assert moderated.json()["moderated_by"] == str(administrator.id)

        deleted = await client.post(
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations/"
            f"{annotations[0].id}/moderation",
            headers=headers,
            json=json_payload({"action": "delete", "version": 2}),
        )
        assert deleted.status_code == 200
        assert deleted.json()["version"] == 3
        assert deleted.json()["authorization"]["allowed"] == []
        remaining = await client.get(
            f"/api/v1/workspaces/{workspace_id}/items/{item.id}/annotations",
            headers=headers,
        )
        assert remaining.status_code == 200
        assert str(annotations[0].id) not in {
            entry["id"] for entry in remaining.json()["annotations"]
        }

    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "annotation.moderate.delete",
            AuditEvent.target_id == str(annotations[0].id),
        )
    )
    assert event is not None
    assert event.authorization_resource_action == "project_annotation.delete"
    assert (event.detail or {})["author_id"] == str(author.id)


@pytest.mark.anyio
@pytest.mark.parametrize("read_only_mode", ["archived", "suspended"])
async def test_http_api_tags_use_effective_management_action(
    async_db, async_session_factory, read_only_mode
):
    db = async_db
    owner = User(username=f"tag-capability-owner-{read_only_mode}", password_hash="unused")
    instance_administrator = User(
        username=f"tag-capability-admin-{read_only_mode}",
        password_hash="unused",
        role=SystemRole.administrator,
    )
    db.add_all([owner, instance_administrator])
    await db.flush()
    await provision_initial_workspace(db, owner)
    workspace_id = fixture_workspace_id(owner)
    tag = Tag(
        workspace_id=workspace_id,
        name="Read only",
        normalized_name="read only",
        created_by=owner.id,
    )
    db.add(tag)
    await db.commit()
    grant = await create_api_token(db, owner, "Read-only Tags", expires_in_days=30)

    if read_only_mode == "archived":
        await archive_workspace(db, owner, workspace_id)
    else:
        await freeze_workspace_governance(db, instance_administrator, workspace_id)

    async with api_client(async_session_factory) as (client, _app):
        response = await client.get(
            f"/api/v1/workspaces/{workspace_id}/tags", headers=bearer(grant.raw_token)
        )

    assert response.status_code == 200
    assert response.json() == json_payload([
        {
            "id": tag.id,
            "name": "Read only",
            "accessible_item_count": 0,
            "authorization": {"allowed": []},
        }
    ])


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
        participation=ProjectParticipation.managed,
    )
    open_project = Project(
        workspace_id=workspace_id,
        name="Open Project",
        created_by=owner.id,
        participation=ProjectParticipation.open,
    )
    archived = Project(
        workspace_id=workspace_id,
        name="Managed archived Project",
        created_by=owner.id,
        participation=ProjectParticipation.managed,
        state=ProjectState.archived,
    )
    workspace_visible = Project(
        workspace_id=workspace_id,
        name="Workspace-visible Project",
        created_by=owner.id,
        participation=ProjectParticipation.workspace,
    )
    db.add_all([active, archived, open_project, workspace_visible])
    await db.commit()
    grant = await create_api_token(db, administrator, "Project governance", expires_in_days=30)
    headers = bearer(grant.raw_token)
    base = f"/api/v1/workspaces/{workspace_id}/projects"

    async with api_client(async_session_factory) as (client, _app):
        projects = await client.get(base, headers=headers)
        assert projects.status_code == 200
        summaries = {project["id"]: project for project in projects.json()["items"]}
        mine = await client.get(f"{base}?view=mine", headers=headers)
        joinable = await client.get(f"{base}?view=joinable", headers=headers)
        invalid_view = await client.get(f"{base}?view=other", headers=headers)
        assert mine.status_code == 200
        assert {project["id"] for project in mine.json()["items"]} == set(
            map(str, {workspace_visible.id})
        )
        assert joinable.status_code == 200
        assert {project["id"] for project in joinable.json()["items"]} == {str(open_project.id)}
        assert joinable.json()["items"][0]["is_participating"] is False
        assert invalid_view.status_code == 422
        active_actions = set(summaries[str(active.id)]["authorization"]["allowed"])
        archived_actions = set(summaries[str(archived.id)]["authorization"]["allowed"])
        assert summaries[str(active.id)]["is_participating"] is False
        assert "project_membership.manage" in active_actions
        assert "project.update" in active_actions
        assert "project.archive" in active_actions
        assert "project.restore" in archived_actions
        assert "project_membership.manage" not in archived_actions
        assert "project.update" not in archived_actions

        active_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert active_detail.status_code == 200
        assert active_detail.json()["active_participants"] == []
        assert active_detail.json()["authorization"] == summaries[str(active.id)]["authorization"]

        workspace_summary = next(
            row for row in projects.json()["items"] if row["id"] == str(workspace_visible.id)
        )
        assert workspace_summary["is_participating"] is True
        assert "project_membership.manage" not in workspace_summary["authorization"]["allowed"]
        workspace_detail = await client.get(f"{base}/{workspace_visible.id}", headers=headers)
        assert workspace_detail.json()["active_participants"] == []
        add_workspace_member = await client.post(
            f"{base}/{workspace_visible.id}/participants",
            headers=headers,
            json=json_payload({"username": administrator.username}),
        )
        remove_workspace_member = await client.delete(
            f"{base}/{workspace_visible.id}/participants/{administrator.id}", headers=headers
        )
        assert add_workspace_member.status_code == 409
        assert add_workspace_member.json()["code"] == "project_member_conflict"
        assert remove_workspace_member.status_code == 409
        assert remove_workspace_member.json()["code"] == "project_member_conflict"

        settings = await client.patch(
            f"{base}/{active.id}",
            headers=headers,
            json=json_payload({
                "name": "Still accessible",
                "description": "",
                "participation": "open",
            }),
        )
        assert settings.status_code == 200
        join = await client.post(f"{base}/{active.id}/join", headers=headers)
        assert join.status_code == 200
        joined_mine = await client.get(f"{base}?view=mine", headers=headers)
        assert {project["id"] for project in joined_mine.json()["items"]} == {
            str(active.id),
            str(workspace_visible.id),
        }
        project_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert project_detail.status_code == 200
        assert project_detail.json()["is_participating"] is True
        leave = await client.post(f"{base}/{active.id}/leave", headers=headers)
        assert leave.status_code == 200
        left_mine = await client.get(f"{base}?view=mine", headers=headers)
        assert {project["id"] for project in left_mine.json()["items"]} == {
            str(workspace_visible.id)
        }
        project_detail = await client.get(f"{base}/{active.id}", headers=headers)
        assert project_detail.status_code == 200
        assert project_detail.json()["is_participating"] is False

        managed_settings = await client.patch(
            f"{base}/{active.id}",
            headers=headers,
            json=json_payload({
                "name": "Still accessible",
                "description": "",
                "participation": "managed",
            }),
        )
        assert managed_settings.status_code == 200
        participant = await client.post(
            f"{base}/{active.id}/participants",
            headers=headers,
            json=json_payload({"username": owner.username}),
        )
        assert participant.status_code == 200
