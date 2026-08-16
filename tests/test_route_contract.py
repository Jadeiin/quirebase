from __future__ import annotations

from test_http import authenticated_client

from quirebase.core.crypto import hash_password
from quirebase.models import DiscussionMessage, Item, Tag, User
from quirebase.web.app import app


def get_app():
    return app


EXPECTED_OPERATIONAL_ROUTES = {
    ("DELETE", "/documents/{item_id}/annotations/{annotation_id}"),
    ("GET", "/"),
    ("GET", "/accept-invitation/{token}"),
    ("GET", "/account/sessions"),
    ("GET", "/admin"),
    ("GET", "/admin/audit"),
    ("GET", "/admin/items"),
    ("GET", "/admin/jobs"),
    ("GET", "/admin/maintenance"),
    ("GET", "/admin/maintenance/backups/{job_id}/download"),
    ("GET", "/admin/settings"),
    ("GET", "/admin/users"),
    ("GET", "/annotation-exports/{job_id}"),
    ("GET", "/annotation-exports/{job_id}/content"),
    ("GET", "/bibliography/export"),
    ("GET", "/bibliography/import"),
    ("GET", "/documents/{item_id}/annotations"),
    ("GET", "/documents/{item_id}/citation"),
    ("GET", "/documents/{item_id}/citation-text"),
    ("GET", "/documents/{item_id}/revisions/{revision_id}/content"),
    ("GET", "/healthz"),
    ("GET", "/items/{item_id}"),
    ("GET", "/items/{item_id}/attachments/{attachment_id}"),
    ("GET", "/items/{item_id}/pdf/{revision_id}"),
    ("GET", "/items/{item_id}/{section}"),
    ("GET", "/library"),
    ("GET", "/login"),
    ("GET", "/metrics"),
    ("GET", "/online-search"),
    ("GET", "/projects"),
    ("GET", "/projects/{project_id}"),
    ("GET", "/tools"),
    ("PATCH", "/documents/{item_id}/annotations/{annotation_id}"),
    ("POST", "/accept-invitation/{token}"),
    ("POST", "/account/sessions/revoke-all"),
    ("POST", "/account/sessions/{session_id}/revoke"),
    ("POST", "/admin/invitations"),
    ("POST", "/admin/items/{item_id}/delete"),
    ("POST", "/admin/jobs/retry-all"),
    ("POST", "/admin/jobs/{job_id}/retry"),
    ("POST", "/admin/maintenance/backup"),
    ("POST", "/admin/maintenance/check-objects"),
    ("POST", "/admin/maintenance/reindex"),
    ("POST", "/admin/settings"),
    ("POST", "/admin/users/create"),
    ("POST", "/admin/users/{user_id}/password"),
    ("POST", "/admin/users/{user_id}/revoke-sessions"),
    ("POST", "/admin/users/{user_id}/role"),
    ("POST", "/admin/users/{user_id}/status"),
    ("POST", "/bibliography/import/{batch_id}"),
    ("POST", "/bibliography/preview"),
    ("POST", "/citation-styles"),
    ("POST", "/citation-styles/{style_id}/delete"),
    ("POST", "/documents/{item_id}/annotation-exports"),
    ("POST", "/documents/{item_id}/annotations"),
    ("POST", "/imports/pdf/published"),
    ("POST", "/imports/pdf/unpublished"),
    ("POST", "/items"),
    ("POST", "/items/{item_id}/attachments"),
    ("POST", "/items/{item_id}/discussion"),
    ("POST", "/items/{item_id}/discussion/{message_id}/delete"),
    ("POST", "/items/{item_id}/edit"),
    ("POST", "/items/{item_id}/pdf"),
    ("POST", "/items/{item_id}/projects/{project_id}"),
    ("POST", "/items/{item_id}/projects/{project_id}/remove"),
    ("POST", "/items/{item_id}/rescan-doi"),
    ("POST", "/items/{item_id}/sync-metadata"),
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
    ("GET", "/api/authors/suggest"),
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

    assert len(operational_routes) == 81, f"Expected 81 routes, found {len(operational_routes)}"
    assert operational_routes == EXPECTED_OPERATIONAL_ROUTES


def test_http_behavioral_contract(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)

    # 1. Non-admin accessing /admin or /metrics returns 404 (hides admin routes)
    admin_resp = client.get("/admin")
    assert admin_resp.status_code == 404

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 404

    # 2. Inaccessible item edits return 404
    other_user = User(
        username="other_user",
        password_hash=hash_password("password1234"),
        role="member",
    )
    db.add(other_user)
    db.flush()
    other_item = Item(title="Private item", created_by=other_user.id)
    db.add(other_item)
    db.commit()

    edit_resp = client.post(
        f"/items/{other_item.id}/edit?csrf_token=test-csrf",
        data={"version": 1, "title": "New Title"},
    )
    assert edit_resp.status_code == 404

    # 3. Version conflict returns 409 with detail {"version": ...}
    conflict_resp = client.post(
        f"/items/{item.id}/edit?csrf_token=test-csrf",
        data={"version": 999, "title": "Conflict Title"},
    )
    assert conflict_resp.status_code == 409
    assert "version" in str(conflict_resp.json())


def test_oversized_bibliography_upload_returns_payload_too_large(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        response = client.post(
            "/bibliography/preview?csrf_token=test-csrf",
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
        assert response.json() == {"detail": "bibliography files are limited to 5 MiB"}
    finally:
        app.dependency_overrides.clear()


def test_tag_rename_conceals_missing_and_foreign_tags(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    other_user = User(username="tag-owner", password_hash="unused")
    db.add(other_user)
    db.flush()
    foreign_tag = Tag(name="Foreign tag", created_by=other_user.id)
    db.add(foreign_tag)
    db.commit()
    try:
        missing = client.post("/tools/tags/missing?csrf_token=test-csrf", data={"name": "Renamed"})
        foreign = client.post(
            f"/tools/tags/{foreign_tag.id}?csrf_token=test-csrf",
            data={"name": "Renamed"},
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        app.dependency_overrides.clear()


def test_tag_delete_conceals_missing_and_foreign_tags(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    other_user = User(username="foreign-tag-owner", password_hash="unused")
    db.add(other_user)
    db.flush()
    foreign_tag = Tag(name="Protected tag", created_by=other_user.id)
    db.add(foreign_tag)
    db.commit()
    try:
        missing = client.post("/tools/tags/missing/delete?csrf_token=test-csrf")
        foreign = client.post(f"/tools/tags/{foreign_tag.id}/delete?csrf_token=test-csrf")

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        app.dependency_overrides.clear()


def test_discussion_delete_conceals_missing_and_foreign_messages(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    other_user = User(username="message-author", password_hash="unused")
    db.add(other_user)
    db.flush()
    foreign_message = DiscussionMessage(
        item_id=item.id, author_id=other_user.id, body="Private authorship"
    )
    db.add(foreign_message)
    db.commit()
    try:
        missing = client.post(f"/items/{item.id}/discussion/missing/delete?csrf_token=test-csrf")
        foreign = client.post(
            f"/items/{item.id}/discussion/{foreign_message.id}/delete?csrf_token=test-csrf"
        )

        assert foreign.status_code == 404
        assert foreign.content == missing.content
    finally:
        app.dependency_overrides.clear()


def test_invitation_creation_is_hidden_from_non_administrators(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        response = client.post(
            "/admin/invitations?csrf_token=test-csrf",
            data={"username": "invitee", "role": "member"},
        )

        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
    finally:
        app.dependency_overrides.clear()


def test_discussion_author_can_delete_own_message(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    own_message = DiscussionMessage(
        item_id=item.id, author_id=item.created_by, body="Finished reviewing"
    )
    db.add(own_message)
    db.commit()
    try:
        response = client.post(
            f"/items/{item.id}/discussion/{own_message.id}/delete?csrf_token=test-csrf",
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/items/{item.id}/discussion"
    finally:
        app.dependency_overrides.clear()


def test_administrator_can_create_invitation(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    administrator = db.get(User, item.created_by)
    administrator.role = "administrator"
    db.commit()
    try:
        response = client.post(
            "/admin/invitations?csrf_token=test-csrf",
            data={"username": "new-member", "role": "member"},
        )

        assert response.status_code == 200
        assert "/accept-invitation/" in response.text
    finally:
        app.dependency_overrides.clear()
