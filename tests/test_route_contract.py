from __future__ import annotations

import pytest
from test_http import authenticated_async_client

from quirebase.core.crypto import hash_password
from quirebase.models import DiscussionMessage, Item, Tag, User
from quirebase.web.app import app


def get_app():
    return app


EXPECTED_OPERATIONAL_ROUTES = {
    ("DELETE", "/api/v1/items/{item_id}/annotations/{annotation_id}"),
    ("DELETE", "/api/v1/items/{item_id}/discussions/{message_id}"),
    ("DELETE", "/api/v1/items/{item_id}/tags/{tag_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/items/{item_id}"),
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"),
    ("DELETE", "/documents/{item_id}/annotations/{annotation_id}"),
    ("GET", "/"),
    ("GET", "/accept-invitation/{token}"),
    ("GET", "/account/sessions"),
    ("GET", "/account/settings"),
    ("GET", "/admin"),
    ("GET", "/admin/audit"),
    ("GET", "/admin/items"),
    ("GET", "/admin/workflows"),
    ("GET", "/admin/maintenance"),
    ("GET", "/admin/maintenance/backups/{workflow_id}/download"),
    ("GET", "/api/workflows/{workflow_id}"),
    ("GET", "/admin/settings"),
    ("GET", "/admin/users"),
    ("GET", "/annotation-exports/{workflow_id}"),
    ("GET", "/annotation-exports/{workflow_id}/content"),
    ("GET", "/bibliography/export"),
    ("GET", "/bibliography/import"),
    ("GET", "/documents/{item_id}/annotations"),
    ("GET", "/documents/{item_id}/citation"),
    ("GET", "/documents/{item_id}/citation-text"),
    ("GET", "/documents/{item_id}/citation-copy"),
    ("GET", "/documents/{item_id}/revisions/{revision_id}/content"),
    ("GET", "/documents/{item_id}/revisions/{revision_id}/export"),
    ("GET", "/documents/{item_id}/revisions/{revision_id}/thumbnail"),
    ("GET", "/documents/{item_id}/thumbnail"),
    ("GET", "/healthz"),
    ("GET", "/imports/{batch_id}/preview"),
    ("POST", "/imports/{batch_id}/retry"),
    ("GET", "/items/{item_id}"),
    ("GET", "/items/{item_id}/attachments/{attachment_id}"),
    ("GET", "/items/{item_id}/download"),
    ("GET", "/items/{item_id}/pdf/{revision_id}"),
    ("GET", "/items/{item_id}/{section}"),
    ("GET", "/api/citation-styles"),
    ("GET", "/api/citation-key-preview"),
    ("GET", "/api/v1/items"),
    ("GET", "/api/v1/items/{item_id}"),
    ("GET", "/api/v1/items/{item_id}/annotations"),
    ("GET", "/api/v1/items/{item_id}/citation"),
    ("GET", "/api/v1/items/{item_id}/discussions"),
    ("GET", "/api/v1/items/{item_id}/documents"),
    ("GET", "/api/v1/projects"),
    ("GET", "/api/v1/projects/{project_id}"),
    ("GET", "/api/v1/tags"),
    ("GET", "/library"),
    ("GET", "/login"),
    ("GET", "/metrics"),
    ("GET", "/online-search"),
    ("GET", "/projects"),
    ("GET", "/projects/{project_id}"),
    ("GET", "/tools"),
    ("PATCH", "/documents/{item_id}/annotations/{annotation_id}"),
    ("PATCH", "/api/v1/items/{item_id}/annotations/{annotation_id}"),
    ("POST", "/accept-invitation/{token}"),
    ("POST", "/account/api-tokens"),
    ("POST", "/account/api-tokens/{token_id}/revoke"),
    ("POST", "/account/sessions/revoke-all"),
    ("POST", "/account/sessions/{session_id}/revoke"),
    ("POST", "/account/settings/locale"),
    ("POST", "/account/settings/password"),
    ("POST", "/api/v1/discovery/search"),
    ("POST", "/api/v1/items"),
    ("POST", "/api/v1/items/{item_id}/annotations"),
    ("POST", "/api/v1/items/{item_id}/discussions"),
    ("POST", "/api/v1/items/{item_id}/tags"),
    ("POST", "/api/v1/projects"),
    ("POST", "/admin/invitations"),
    ("POST", "/admin/items/{item_id}/delete"),
    ("POST", "/admin/maintenance/backup"),
    ("POST", "/admin/maintenance/check-objects"),
    ("POST", "/admin/maintenance/reindex"),
    ("POST", "/admin/maintenance/recommend-tags"),
    ("POST", "/admin/settings"),
    ("POST", "/admin/users/create"),
    ("POST", "/admin/users/{user_id}/password"),
    ("POST", "/admin/users/{user_id}/revoke-sessions"),
    ("POST", "/admin/users/{user_id}/role"),
    ("POST", "/admin/users/{user_id}/status"),
    ("POST", "/bibliography/import/{batch_id}"),
    ("POST", "/bibliography/import/{batch_id}/discard"),
    ("POST", "/bibliography/preview"),
    ("POST", "/citation-styles"),
    ("POST", "/citation-styles/{style_id}/delete"),
    ("POST", "/documents/{item_id}/annotation-exports"),
    ("POST", "/documents/{item_id}/annotations"),
    ("POST", "/imports/pdf/published"),
    ("POST", "/items"),
    ("POST", "/items/{item_id}/attachments"),
    ("POST", "/items/{item_id}/attachments/{attachment_id}/delete"),
    ("POST", "/items/{item_id}/discussion"),
    ("POST", "/items/{item_id}/discussion/{message_id}/delete"),
    ("POST", "/items/{item_id}/edit"),
    ("POST", "/items/{item_id}/delete"),
    ("POST", "/items/{item_id}/pdf"),
    ("POST", "/items/{item_id}/pdf/{revision_id}/delete"),
    ("POST", "/items/{item_id}/projects/{project_id}"),
    ("POST", "/items/{item_id}/projects/{project_id}/remove"),
    ("POST", "/items/{item_id}/rescan-doi"),
    ("POST", "/items/{item_id}/sync-metadata"),
    ("POST", "/items/{item_id}/tag-recommendations"),
    ("POST", "/items/{item_id}/tags"),
    ("POST", "/items/{item_id}/tags/matrix"),
    ("POST", "/items/{item_id}/tags/{tag_id}/remove"),
    ("POST", "/items/{item_id}/update-bibtex-key"),
    ("POST", "/library/bulk"),
    ("POST", "/login"),
    ("POST", "/logout"),
    ("POST", "/metadata/preview"),
    ("POST", "/projects"),
    ("POST", "/projects/{project_id}/members"),
    ("POST", "/projects/{project_id}/members/{member_id}/remove"),
    ("POST", "/tools/tags/{tag_id}"),
    ("POST", "/tools/tags/{tag_id}/delete"),
    ("POST", "/tools/tags/merge"),
    ("GET", "/api/authors/suggest"),
    ("PUT", "/api/v1/items/{item_id}"),
    ("PUT", "/api/v1/items/{item_id}/tags"),
    ("PUT", "/api/v1/projects/{project_id}/items/{item_id}"),
    ("PUT", "/api/v1/projects/{project_id}/members"),
}


def _extract_routes(routes):
    out = []
    for r in routes:
        if hasattr(r, "original_router"):
            out.extend(_extract_routes(r.original_router.routes))
        elif hasattr(r, "routes"):
            out.extend(_extract_routes(r.routes))
        elif hasattr(r, "methods") and hasattr(r, "path"):
            out.append(r)
    return out


def test_operational_routes_contract():
    test_app = get_app()
    excluded_paths = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}
    operational_routes: set[tuple[str, str]] = set()

    for route in _extract_routes(test_app.routes):
        if route.path in excluded_paths:
            continue
        for method in route.methods:
            if method == "HEAD":
                continue
            operational_routes.add((method, route.path))

    assert len(operational_routes) == 125, f"Expected 125 routes, found {len(operational_routes)}"
    assert operational_routes == EXPECTED_OPERATIONAL_ROUTES


@pytest.mark.anyio
async def test_http_behavioral_contract(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id

    # 1. Non-admin accessing /admin or /metrics returns 404 (hides admin routes)
    admin_resp = await client.get("/admin")
    assert admin_resp.status_code == 404

    metrics_resp = await client.get("/metrics")
    assert metrics_resp.status_code == 404

    # 2. Inaccessible item edits return 404
    other_user = User(
        username="other_user",
        password_hash=hash_password("password1234"),
        role="member",
    )
    db.add(other_user)
    await db.flush()
    other_item = Item(title="Private item", created_by=other_user.id)
    db.add(other_item)
    await db.commit()

    edit_resp = await client.post(
        f"/items/{other_item.id}/edit",
        data={"csrf_token": "test-csrf", "version": 1, "title": "New Title"},
    )
    assert edit_resp.status_code == 404

    # 3. Version conflict returns 409 with detail {"version": ...}
    conflict_resp = await client.post(
        f"/items/{item_id}/edit",
        data={"csrf_token": "test-csrf", "version": 999, "title": "Conflict Title"},
    )
    assert conflict_resp.status_code == 409
    assert "version" in str(conflict_resp.json())
    await client.aclose()


@pytest.mark.anyio
async def test_oversized_bibliography_upload_returns_payload_too_large(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            "/bibliography/preview",
            data={"csrf_token": "test-csrf", "file_format": "bibtex"},
            files={
                "bibliography": (
                    "oversized.bib",
                    b"x" * (5 * 1024 * 1024 + 1),
                    "application/x-bibtex",
                )
            },
        )

        assert response.status_code == 413
        assert response.json() == {"detail": "bibliography files are limited to 5 MiB"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_tag_rename_conceals_missing_and_foreign_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, _item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="tag-owner", password_hash="unused")
    db.add(other_user)
    await db.flush()
    foreign_tag = Tag(name="Foreign tag", created_by=other_user.id)
    db.add(foreign_tag)
    await db.commit()
    try:
        missing = await client.post(
            "/tools/tags/missing", data={"csrf_token": "test-csrf", "name": "Renamed"}
        )
        foreign = await client.post(
            f"/tools/tags/{foreign_tag.id}",
            data={"csrf_token": "test-csrf", "name": "Renamed"},
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_tag_delete_conceals_missing_and_foreign_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, _item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="foreign-tag-owner", password_hash="unused")
    db.add(other_user)
    await db.flush()
    foreign_tag = Tag(name="Protected tag", created_by=other_user.id)
    db.add(foreign_tag)
    await db.commit()
    try:
        missing = await client.post("/tools/tags/missing/delete", data={"csrf_token": "test-csrf"})
        foreign = await client.post(
            f"/tools/tags/{foreign_tag.id}/delete", data={"csrf_token": "test-csrf"}
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_discussion_delete_conceals_missing_and_foreign_messages(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="message-author", password_hash="unused")
    db.add(other_user)
    await db.flush()
    foreign_message = DiscussionMessage(
        item_id=item.id, author_id=other_user.id, body="Private authorship"
    )
    db.add(foreign_message)
    await db.commit()
    try:
        missing = await client.post(
            f"/items/{item.id}/discussion/missing/delete", data={"csrf_token": "test-csrf"}
        )
        foreign = await client.post(
            f"/items/{item.id}/discussion/{foreign_message.id}/delete",
            data={"csrf_token": "test-csrf"},
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_invitation_creation_is_hidden_from_non_administrators(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            "/admin/invitations",
            data={"csrf_token": "test-csrf", "username": "invitee", "role": "member"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_mutation_is_hidden_before_csrf_validation(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            "/admin/invitations",
            data={"username": "invitee", "role": "member"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_discussion_author_can_delete_own_message(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    own_message = DiscussionMessage(
        item_id=item.id, author_id=item.created_by, body="Finished reviewing"
    )
    db.add(own_message)
    await db.commit()
    try:
        response = await client.post(
            f"/items/{item.id}/discussion/{own_message.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/items/{item.id}/discussion"
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_administrator_can_create_invitation(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    administrator = await db.get(User, item.created_by)
    assert administrator is not None
    administrator.role = "administrator"
    await db.commit()
    try:
        response = await client.post(
            "/admin/invitations",
            data={"csrf_token": "test-csrf", "username": "new-member", "role": "member"},
        )

        assert response.status_code == 200
        assert "/accept-invitation/" in response.text
    finally:
        await client.aclose()
