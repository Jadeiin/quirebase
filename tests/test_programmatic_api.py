from __future__ import annotations

import json
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx2
import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from quirebase.accounts import create_api_token
from quirebase.core.database import get_db
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    AuditEvent,
    FileRevision,
    Item,
    PdfAnnotation,
    Project,
    ProjectItem,
    SystemRole,
    User,
)
from quirebase.programmatic import (
    DocumentListView,
    ItemDetailView,
    LibrarySearchView,
    ProjectDetailView,
)
from quirebase.web.api.routes import router as programmatic_api_router
from quirebase.web.app import create_app


@asynccontextmanager
async def api_client(factory):
    app = create_app(mcp_session_factory=factory)

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
    await db.commit()
    grant = await create_api_token(db, user, "HTTP API", expires_in_days=30)

    async with api_client(async_session_factory) as (client, _app):
        client.cookies.set("quirebase_session", "not-an-api-credential")
        missing = await client.get("/api/v1/items")
        query = await client.get(f"/api/v1/items?token={grant.raw_token}")
        invalid = await client.get("/api/v1/items", headers=bearer("invalid"))
        accepted = await client.get("/api/v1/items", headers=bearer(grant.raw_token))

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert query.status_code == 401
    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"items": [], "total": 0, "page": 1, "per_page": 25}


@pytest.mark.anyio
async def test_http_api_exposes_the_same_ordinary_user_capability_set_as_mcp(
    async_session_factory,
):
    expected = {
        ("GET", "/api/v1/items"),
        ("POST", "/api/v1/items"),
        ("GET", "/api/v1/items/{item_id}"),
        ("PUT", "/api/v1/items/{item_id}"),
        ("GET", "/api/v1/items/{item_id}/citation"),
        ("GET", "/api/v1/projects"),
        ("POST", "/api/v1/projects"),
        ("GET", "/api/v1/projects/{project_id}"),
        ("PUT", "/api/v1/projects/{project_id}/items/{item_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/items/{item_id}"),
        ("PUT", "/api/v1/projects/{project_id}/members"),
        ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"),
        ("GET", "/api/v1/items/{item_id}/documents"),
        ("GET", "/api/v1/items/{item_id}/annotations"),
        ("POST", "/api/v1/items/{item_id}/annotations"),
        ("PATCH", "/api/v1/items/{item_id}/annotations/{annotation_id}"),
        ("DELETE", "/api/v1/items/{item_id}/annotations/{annotation_id}"),
        ("POST", "/api/v1/items/{item_id}/annotations/{annotation_id}/replies"),
        (
            "PATCH",
            "/api/v1/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
        ),
        (
            "DELETE",
            "/api/v1/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
        ),
        ("GET", "/api/v1/tags"),
        ("POST", "/api/v1/items/{item_id}/tags"),
        ("DELETE", "/api/v1/items/{item_id}/tags/{tag_id}"),
        ("PUT", "/api/v1/items/{item_id}/tags"),
        ("GET", "/api/v1/items/{item_id}/discussions"),
        ("POST", "/api/v1/items/{item_id}/discussions"),
        ("DELETE", "/api/v1/items/{item_id}/discussions/{message_id}"),
        ("POST", "/api/v1/discovery/search"),
    }

    async with api_client(async_session_factory) as (_client, _app):
        actual = {
            (method, route.path)
            for route in programmatic_api_router.routes
            if isinstance(route, APIRoute)
            for method in route.methods or set()
        }
        response_models = {
            (next(iter(route.methods or set())), route.path): route.response_model
            for route in programmatic_api_router.routes
            if isinstance(route, APIRoute) and route.methods
        }

    assert actual == expected
    assert response_models["GET", "/api/v1/items"] is LibrarySearchView
    assert response_models["GET", "/api/v1/items/{item_id}"] is ItemDetailView
    assert response_models["GET", "/api/v1/projects/{project_id}"] is ProjectDetailView
    assert response_models["GET", "/api/v1/items/{item_id}/documents"] is DocumentListView


@pytest.mark.anyio
async def test_http_api_library_project_tag_and_discussion_lifecycle(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="api-lifecycle", password_hash="unused")
    db.add(user)
    await db.commit()
    grant = await create_api_token(db, user, "Lifecycle", expires_in_days=30)
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        created = await client.post(
            "/api/v1/items",
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

        listed = await client.get("/api/v1/items?query=HTTP", headers=headers)
        detail = await client.get(f"/api/v1/items/{item_id}", headers=headers)
        assert listed.json()["items"][0]["id"] == item_id
        assert detail.json()["metadata"]["custom_fields"] == [{"name": "rating", "value": 5}]

        metadata = detail.json()["metadata"]
        metadata["title"] = "Updated through HTTP API"
        updated = await client.put(
            f"/api/v1/items/{item_id}",
            headers=headers,
            json={"expected_version": detail.json()["version"], "metadata": metadata},
        )
        assert updated.status_code == 200

        project = await client.post(
            "/api/v1/projects", headers=headers, json={"name": "API Project"}
        )
        project_id = project.json()["id"]
        assert (
            await client.put(f"/api/v1/projects/{project_id}/items/{item_id}", headers=headers)
        ).json() == {"ok": True}
        assert (await client.get(f"/api/v1/projects/{project_id}", headers=headers)).json()[
            "item_count"
        ] == 1

        tag = await client.post(
            f"/api/v1/items/{item_id}/tags", headers=headers, json={"name": "Reviewed"}
        )
        assert tag.status_code == 200
        assert (await client.get("/api/v1/tags", headers=headers)).json()[0]["name"] == "Reviewed"

        discussion = await client.post(
            f"/api/v1/items/{item_id}/discussions",
            headers=headers,
            json={"body": "Programmatic note"},
        )
        assert discussion.status_code == 201
        message_id = discussion.json()["id"]
        assert (await client.get(f"/api/v1/items/{item_id}/discussions", headers=headers)).json()[
            0
        ]["body"] == "Programmatic note"
        assert (
            await client.delete(
                f"/api/v1/items/{item_id}/discussions/{message_id}", headers=headers
            )
        ).json() == {"ok": True}


@pytest.mark.anyio
async def test_http_api_document_and_annotation_views_match_programmatic_contracts(
    async_db, async_session_factory
):
    db = async_db
    user = User(username="api-annotations", password_hash="unused")
    db.add(user)
    await db.flush()
    item_response_title = "Annotated Item"
    await db.commit()
    user_id = user.id
    grant = await create_api_token(db, user, "Annotations", expires_in_days=30)
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        item_id = (
            await client.post("/api/v1/items", headers=headers, json={"title": item_response_title})
        ).json()["id"]

    revision = FileRevision(
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
        documents = await client.get(f"/api/v1/items/{item_id}/documents", headers=headers)
        assert documents.status_code == 200
        assert documents.json()["files"][0]["original_name"] == "api.pdf"

        created = await client.post(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": str(uuid4()),
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
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
            f"/api/v1/items/{item_id}/annotations/{annotation_id}/replies",
            headers=headers,
            json={"id": annotation_id, "body": "Conflicting reply ID"},
        )
        assert root_id_as_reply.status_code == 409
        reply_id = str(uuid4())
        created_reply = await client.post(
            f"/api/v1/items/{item_id}/annotations/{annotation_id}/replies",
            headers=headers,
            json={"id": reply_id, "body": "API reply"},
        )
        assert created_reply.status_code == 201
        assert created_reply.json()["body"] == "API reply"
        reply_id_as_root = await client.post(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": reply_id,
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "body": "Conflicting annotation ID",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
                },
            },
        )
        assert reply_id_as_root.status_code == 409
        listed = await client.get(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            params={"revision_id": revision.id},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == annotation_id
        assert listed.json()[0]["replies"][0]["id"] == reply_id
        updated_reply = await client.patch(
            f"/api/v1/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
            headers=headers,
            json={"version": 1, "body": "Updated API reply"},
        )
        assert updated_reply.status_code == 200
        assert updated_reply.json()["version"] == 2
        updated = await client.patch(
            f"/api/v1/items/{item_id}/annotations/{annotation_id}",
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
            f"/api/v1/items/{item_id}/annotations/{annotation_id}/replies/{reply_id}",
            headers=headers,
            params={"version": 2},
        )
        assert deleted_reply.status_code == 200
        deleted_reply_id_as_root = await client.post(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            json={
                "id": reply_id,
                "revision_id": revision.id,
                "page_index": 0,
                "kind": "note",
                "body": "Still conflicting after soft deletion",
                "payload": {
                    "type": "note",
                    "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
                },
            },
        )
        assert deleted_reply_id_as_root.status_code == 409
        conflict = await client.delete(
            f"/api/v1/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            params={"version": 1},
        )
        assert conflict.status_code == 409
        deleted = await client.delete(
            f"/api/v1/items/{item_id}/annotations/{annotation_id}",
            headers=headers,
            params={"version": 2},
        )
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True}
        assert (
            await client.get(
                f"/api/v1/items/{item_id}/annotations",
                headers=headers,
                params={"revision_id": revision.id},
            )
        ).json() == []


@pytest.mark.anyio
async def test_administrator_can_update_and_delete_other_users_annotations_via_http_api(
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
    item = Item(title="Administrator annotation access", created_by=author.id)
    project = Project(name="Unjoined annotation project", created_by=author.id)
    db.add_all([item, project])
    await db.flush()
    revision = FileRevision(
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
    db.add_all([revision, ProjectItem(project_id=project.id, item_id=item.id)])
    await db.flush()
    payload = {
        "type": "note",
        "rect": {"x": 10, "y": 20, "width": 24, "height": 24},
    }
    annotations = [
        PdfAnnotation(
            file_revision_id=revision.id,
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.private,
            payload=payload,
        ),
        PdfAnnotation(
            file_revision_id=revision.id,
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_id=project.id,
            payload=payload,
        ),
    ]
    db.add_all(annotations)
    await db.commit()
    grant = await create_api_token(
        db, administrator, "Administrator annotations", expires_in_days=30
    )
    headers = bearer(grant.raw_token)

    async with api_client(async_session_factory) as (client, _app):
        for annotation in annotations:
            updated = await client.patch(
                f"/api/v1/items/{item.id}/annotations/{annotation.id}",
                headers=headers,
                json={
                    "version": 1,
                    "page_index": 0,
                    "kind": "note",
                    "scope": annotation.scope,
                    "project_id": annotation.project_id,
                    "body": "Updated by administrator",
                    "payload": payload,
                },
            )
            assert updated.status_code == 200
            assert updated.json()["body"] == "Updated by administrator"

            deleted = await client.delete(
                f"/api/v1/items/{item.id}/annotations/{annotation.id}",
                headers=headers,
                params={"version": 2},
            )
            assert deleted.status_code == 200
            assert deleted.json() == {"ok": True}
