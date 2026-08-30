from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from quirebase.accounts import create_api_token
from quirebase.core.database import get_db
from quirebase.models import AuditEvent, FileRevision, User
from quirebase.programmatic import (
    DocumentListView,
    ItemDetailView,
    LibrarySearchView,
    ProjectDetailView,
)
from quirebase.web.api.routes import router as programmatic_api_router
from quirebase.web.app import create_app


@contextmanager
def api_client(db):
    factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    app = create_app(mcp_session_factory=factory)

    def override_db():
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, app


def bearer(raw_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_token}"}


def test_http_api_requires_a_bearer_api_token_and_rejects_cookie_or_query_token(db):
    user = User(username="api-auth-user", password_hash="unused")
    db.add(user)
    db.commit()
    grant = create_api_token(db, user, "HTTP API", expires_in_days=30)

    with api_client(db) as (client, _app):
        client.cookies.set("quirebase_session", "not-an-api-credential")
        missing = client.get("/api/v1/items")
        query = client.get(f"/api/v1/items?token={grant.raw_token}")
        invalid = client.get("/api/v1/items", headers=bearer("invalid"))
        accepted = client.get("/api/v1/items", headers=bearer(grant.raw_token))

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert query.status_code == 401
    assert invalid.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"items": [], "total": 0, "page": 1, "per_page": 25}


def test_http_api_exposes_the_same_ordinary_user_capability_set_as_mcp(db):
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
        ("GET", "/api/v1/tags"),
        ("POST", "/api/v1/items/{item_id}/tags"),
        ("DELETE", "/api/v1/items/{item_id}/tags/{tag_id}"),
        ("PUT", "/api/v1/items/{item_id}/tags"),
        ("GET", "/api/v1/items/{item_id}/discussions"),
        ("POST", "/api/v1/items/{item_id}/discussions"),
        ("DELETE", "/api/v1/items/{item_id}/discussions/{message_id}"),
        ("POST", "/api/v1/discovery/search"),
    }

    with api_client(db) as (_client, _app):
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


def test_http_api_library_project_tag_and_discussion_lifecycle(db):
    user = User(username="api-lifecycle", password_hash="unused")
    db.add(user)
    db.commit()
    grant = create_api_token(db, user, "Lifecycle", expires_in_days=30)
    headers = bearer(grant.raw_token)

    with api_client(db) as (client, _app):
        created = client.post(
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
        event = db.query(AuditEvent).filter_by(action="item.create", target_id=item_id).one()
        assert json.loads(event.detail) == {
            "invocation": {
                "protocol": "http",
                "operation": "create_library_item",
                "api_token_id": grant.token_id,
                "client_id": "http-api",
            }
        }

        listed = client.get("/api/v1/items?query=HTTP", headers=headers)
        detail = client.get(f"/api/v1/items/{item_id}", headers=headers)
        assert listed.json()["items"][0]["id"] == item_id
        assert detail.json()["metadata"]["custom_fields"] == [{"name": "rating", "value": 5}]

        metadata = detail.json()["metadata"]
        metadata["title"] = "Updated through HTTP API"
        updated = client.put(
            f"/api/v1/items/{item_id}",
            headers=headers,
            json={"expected_version": detail.json()["version"], "metadata": metadata},
        )
        assert updated.status_code == 200

        project = client.post("/api/v1/projects", headers=headers, json={"name": "API Project"})
        project_id = project.json()["id"]
        assert client.put(
            f"/api/v1/projects/{project_id}/items/{item_id}", headers=headers
        ).json() == {"ok": True}
        assert (
            client.get(f"/api/v1/projects/{project_id}", headers=headers).json()["item_count"] == 1
        )

        tag = client.post(
            f"/api/v1/items/{item_id}/tags", headers=headers, json={"name": "Reviewed"}
        )
        assert tag.status_code == 200
        assert client.get("/api/v1/tags", headers=headers).json()[0]["name"] == "Reviewed"

        discussion = client.post(
            f"/api/v1/items/{item_id}/discussions",
            headers=headers,
            json={"body": "Programmatic note"},
        )
        assert discussion.status_code == 201
        message_id = discussion.json()["id"]
        assert (
            client.get(f"/api/v1/items/{item_id}/discussions", headers=headers).json()[0]["body"]
            == "Programmatic note"
        )
        assert client.delete(
            f"/api/v1/items/{item_id}/discussions/{message_id}", headers=headers
        ).json() == {"ok": True}


def test_http_api_document_and_annotation_views_match_programmatic_contracts(db):
    user = User(username="api-annotations", password_hash="unused")
    db.add(user)
    db.flush()
    item_response_title = "Annotated Item"
    db.commit()
    grant = create_api_token(db, user, "Annotations", expires_in_days=30)
    headers = bearer(grant.raw_token)

    with api_client(db) as (client, _app):
        item_id = client.post(
            "/api/v1/items", headers=headers, json={"title": item_response_title}
        ).json()["id"]

    revision = FileRevision(
        item_id=item_id,
        object_key="objects/api.pdf",
        sha256="a" * 64,
        size=100,
        mime_type="application/pdf",
        original_name="api.pdf",
        page_count=1,
        page_geometry="[[0, 0, 100, 100]]",
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    db.commit()

    with api_client(db) as (client, _app):
        documents = client.get(f"/api/v1/items/{item_id}/documents", headers=headers)
        assert documents.status_code == 200
        assert documents.json()["files"][0]["original_name"] == "api.pdf"

        created = client.post(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            json={
                "revision_id": revision.id,
                "kind": "note",
                "segments": [{"page_index": 0, "anchor_x": 10, "anchor_y": 20}],
                "body": "API annotation",
            },
        )
        assert created.status_code == 201
        annotation_id = created.json()["id"]
        listed = client.get(
            f"/api/v1/items/{item_id}/annotations",
            headers=headers,
            params={"revision_id": revision.id},
        )
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == annotation_id
