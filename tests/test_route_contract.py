from __future__ import annotations

import pytest
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.crypto import hash_password
from quirebase.models import DiscussionMessage, Item, Tag, User
from quirebase.web.app import app


def get_app():
    return app


def test_operational_routes_contract():
    test_app = get_app()
    excluded_paths = {"/docs", "/docs/oauth2-redirect", "/openapi.json", "/redoc"}

    # OpenAPI contains the effective paths after FastAPI composes the versioned
    # router. Inspect direct application routes separately for the SPA fallback
    # and other non-schema operational methods; child router internals contain
    # relative paths by design.
    operational_routes: set[tuple[str, str]] = {
        (method.upper(), path)
        for path, methods in test_app.openapi()["paths"].items()
        for method in methods
        if method in {"get", "post", "put", "patch", "delete"}
    }
    for route in test_app.routes:
        if not hasattr(route, "methods") or not hasattr(route, "path"):
            continue
        if route.path in excluded_paths:
            continue
        for method in route.methods:
            if method != "HEAD":
                operational_routes.add((method, route.path))

    assert {
        ("POST", "/api/v1/workspaces/{workspace_id}/items/{item_id}/attachments/remote"),
        ("POST", "/api/v1/workspaces/{workspace_id}/items/{item_id}/revisions/remote"),
    } <= operational_routes
    assert all(
        path.startswith("/api/v1") or path in {"/healthz", "/metrics"}
        for _method, path in operational_routes
    )


@pytest.mark.anyio
async def test_http_behavioral_contract(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    item_id = item.id
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"

    # 1. Non-admin access to the administration API is concealed.
    admin_resp = await client.get("/api/v1/admin/overview")
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
    await provision_initial_workspace(db, other_user)
    other_item = Item(
        workspace_id=fixture_workspace_id(other_user),
        title="Private item",
        created_by=other_user.id,
    )
    db.add(other_item)
    await db.commit()

    edit_resp = await client.put(
        f"{workspace_base}/items/{other_item.id}",
        json={"expected_version": 1, "metadata": {"title": "New Title"}},
    )
    assert edit_resp.status_code == 404

    # 3. Version conflict returns the current version as structured metadata.
    conflict_resp = await client.put(
        f"{workspace_base}/items/{item_id}",
        json={"expected_version": 999, "metadata": {"title": "Conflict Title"}},
    )
    assert conflict_resp.status_code == 409
    assert conflict_resp.json() == {
        "code": "version_conflict",
        "message": "version conflict, current version is 1",
        "meta": {"version": 1},
    }
    await client.aclose()


@pytest.mark.anyio
async def test_oversized_bibliography_upload_returns_payload_too_large(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        response = await client.post(
            f"{workspace_base}/imports/bibliography",
            data={"file_format": "bibtex"},
            files={
                "bibliography": (
                    "oversized.bib",
                    b"x" * (5 * 1024 * 1024 + 1),
                    "application/x-bibtex",
                )
            },
        )

        assert response.status_code == 413
        assert response.json() == {
            "code": "content_too_large",
            "message": "bibliography files are limited to 5 MiB",
        }
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_tag_rename_conceals_missing_and_foreign_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    other_user = User(username="tag-owner", password_hash="unused")
    db.add(other_user)
    await db.flush()
    await provision_initial_workspace(db, other_user)
    foreign_tag = Tag(
        workspace_id=fixture_workspace_id(other_user),
        name="Foreign tag",
        created_by=other_user.id,
    )
    db.add(foreign_tag)
    await db.commit()
    try:
        missing = await client.patch(f"{workspace_base}/tags/missing", json={"name": "Renamed"})
        foreign = await client.patch(
            f"{workspace_base}/tags/{foreign_tag.id}", json={"name": "Renamed"}
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
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    other_user = User(username="foreign-tag-owner", password_hash="unused")
    db.add(other_user)
    await db.flush()
    await provision_initial_workspace(db, other_user)
    foreign_tag = Tag(
        workspace_id=fixture_workspace_id(other_user),
        name="Protected tag",
        created_by=other_user.id,
    )
    db.add(foreign_tag)
    await db.commit()
    try:
        missing = await client.delete(f"{workspace_base}/tags/missing")
        foreign = await client.delete(f"{workspace_base}/tags/{foreign_tag.id}")

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_tag_list_conceals_tags_without_accessible_items(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    other_user = User(username="prolific-tagger", password_hash="unused")
    db.add(other_user)
    await db.flush()
    await provision_initial_workspace(db, other_user)
    foreign_tag = Tag(
        workspace_id=fixture_workspace_id(other_user),
        name="Foreign private taxonomy",
        created_by=other_user.id,
    )
    own_tag = Tag(
        workspace_id=item.workspace_id,
        name="Own empty taxonomy",
        created_by=item.created_by,
    )
    db.add_all([foreign_tag, own_tag])
    await db.commit()
    try:
        listing = await client.get(f"{workspace_base}/tags")

        assert listing.status_code == 200
        names = [row["name"] for row in listing.json()]
        assert "Foreign private taxonomy" not in names
        assert "Own empty taxonomy" in names
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
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    other_user = User(username="message-author", password_hash="unused")
    db.add(other_user)
    await db.flush()
    foreign_message = DiscussionMessage(
        workspace_id=item.workspace_id,
        item_id=item.id,
        author_id=other_user.id,
        body="Private authorship",
    )
    db.add(foreign_message)
    await db.commit()
    try:
        missing = await client.delete(f"{workspace_base}/items/{item.id}/discussions/missing")
        foreign = await client.delete(
            f"{workspace_base}/items/{item.id}/discussions/{foreign_message.id}"
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_workspace_owner_moderates_foreign_item_discussion_with_reason(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    other_user = User(username="moderated-author", password_hash="unused")
    db.add(other_user)
    await db.flush()
    message = DiscussionMessage(
        workspace_id=item.workspace_id,
        item_id=item.id,
        author_id=other_user.id,
        body="Remove this message",
    )
    db.add(message)
    await db.commit()
    base = f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/discussions"
    try:
        listing = await client.get(base)
        assert listing.status_code == 200
        assert listing.json()[0]["allowed_actions"] == ["moderate"]
        invalid = await client.post(f"{base}/{message.id}/moderation", json={"reason": "  "})
        assert invalid.status_code == 422
        response = await client.post(
            f"{base}/{message.id}/moderation", json={"reason": "Policy violation"}
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True}
        assert await db.get(DiscussionMessage, message.id, populate_existing=True) is None
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
            "/api/v1/admin/invitations",
            json={"username": "invitee", "role": "member"},
        )

        assert response.status_code == 404
        assert response.json() == {"code": "not_found", "message": "resource not found"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_admin_mutation_requires_same_origin_before_authorization(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            "/api/v1/admin/invitations",
            headers={"Origin": "https://attacker.example"},
            json={"username": "invitee", "role": "member"},
        )

        assert response.status_code == 403
        assert response.json() == {
            "code": "origin_mismatch",
            "message": "origin does not match request origin",
        }
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
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    own_message = DiscussionMessage(
        workspace_id=item.workspace_id,
        item_id=item.id,
        author_id=item.created_by,
        body="Finished reviewing",
    )
    db.add(own_message)
    await db.commit()
    try:
        response = await client.delete(
            f"{workspace_base}/items/{item.id}/discussions/{own_message.id}"
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True}
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
            "/api/v1/admin/invitations",
            json={"username": "new-member", "role": "member"},
        )

        assert response.status_code == 201
        assert response.json()["accept_path"] == f"/invite/{response.json()['token']}"
    finally:
        await client.aclose()
