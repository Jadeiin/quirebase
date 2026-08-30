"""Security regression tests for the session-bound CSRF contract.

The route policy lives in ``quirebase.web.deps``: every cookie-authenticated
unsafe (POST/PUT/PATCH/DELETE) endpoint is covered by either the shared
``require_csrf`` dependency through ``protected_router`` or the Bearer-only
``current_api_user`` dependency. Pre-authentication mutations are enumerated here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from test_http import authenticated_client

from quirebase.core.crypto import token_hash
from quirebase.models import LoginSession, Tag, User
from quirebase.web.app import app

# Unsafe endpoints reachable WITHOUT a Login Session. Anything added here is a
# deliberate CSRF-policy exception and needs its own justification and tests.
PUBLIC_UNSAFE_ROUTES = {
    ("POST", "/login"),
    ("POST", "/accept-invitation/{token}"),
}


def extract_routes(routes):
    for route in routes:
        if hasattr(route, "original_router"):
            yield from extract_routes(route.original_router.routes)
        elif hasattr(route, "routes"):
            yield from extract_routes(route.routes)
        elif hasattr(route, "methods") and hasattr(route, "path"):
            yield route


def dependency_names(route) -> set[str]:
    names: set[str] = set()

    def walk(dep) -> None:
        if callable(dep.call):
            names.add(getattr(dep.call, "__name__", type(dep.call).__name__))
        for sub in dep.dependencies:
            walk(sub)

    walk(route.dependant)
    return names


def test_every_unsafe_route_is_covered_by_the_csrf_policy():
    uncovered_public: set[tuple[str, str]] = set()
    for route in extract_routes(app.routes):
        methods = route.methods - {"HEAD"}
        if not methods or not hasattr(route, "dependant"):
            continue
        if not any(method in ("POST", "PUT", "PATCH", "DELETE") for method in methods):
            continue
        dependencies = dependency_names(route)
        if not dependencies.intersection({"require_csrf", "current_api_user"}):
            uncovered_public.add((min(methods), route.path))
    assert uncovered_public == PUBLIC_UNSAFE_ROUTES


def test_unsafe_methods_reject_missing_wrong_and_foreign_tokens(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        other_user = User(username="elsewhere", password_hash="unused")
        db.add(other_user)
        db.flush()
        other_login = LoginSession(
            token_hash=token_hash("other-session"),
            csrf_token="other-csrf",
            user_id=other_user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(other_login)
        db.commit()

        missing = client.post(f"/items/{item.id}/tags", data={"name": "No token"})
        wrong = client.post(
            f"/items/{item.id}/tags", data={"csrf_token": "not-the-token", "name": "Bad"}
        )
        foreign = client.post(
            f"/items/{item.id}/tags",
            headers={"X-CSRF-Token": "other-csrf"},
            data={"name": "Foreign session"},
        )
        query = client.post(f"/items/{item.id}/tags?csrf_token=test-csrf", data={"name": "URL"})

        assert missing.status_code == 403
        assert wrong.status_code == 403
        assert foreign.status_code == 403
        assert query.status_code == 403
        assert db.query(Tag).count() == 0
    finally:
        app.dependency_overrides.clear()


def test_header_and_form_tokens_are_accepted_for_every_transport(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        header_urlencoded = client.post(
            f"/items/{item.id}/tags",
            headers={"X-CSRF-Token": "test-csrf"},
            data={"name": "Header token"},
        )
        form_urlencoded = client.post(
            f"/items/{item.id}/tags", data={"csrf_token": "test-csrf", "name": "Form token"}
        )
        form_multipart = client.post(
            f"/items/{item.id}/attachments",
            files={"attachment": ("notes.txt", b"supplement", "text/plain")},
            data={"csrf_token": "test-csrf"},
        )
        header_json = client.post(
            f"/documents/{item.id}/annotation-exports",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"revision_id": revision.id, "format": "pdf", "timezone": ""},
        )

        assert header_urlencoded.status_code == 200
        assert form_urlencoded.status_code == 200
        assert form_multipart.status_code == 200
        assert header_json.status_code in (200, 201, 202, 303)
    finally:
        app.dependency_overrides.clear()


def test_multipart_token_must_arrive_with_the_form_not_the_query(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        query_only = client.post(
            f"/items/{item.id}/attachments?csrf_token=test-csrf",
            files={"attachment": ("notes.txt", b"supplement", "text/plain")},
        )
        assert query_only.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_revoked_session_invalidates_its_token(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        client.post("/account/sessions/revoke-all", data={"csrf_token": "test-csrf"})
        db.expire_all()
        after_revoke = client.post(
            f"/items/{item.id}/tags",
            headers={"X-CSRF-Token": "test-csrf"},
            data={"name": "After revoke"},
        )
        assert after_revoke.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()


def test_safe_methods_do_not_require_a_token(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        assert client.get(f"/items/{item.id}").status_code == 200
        assert client.get("/library").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_tokens_never_appear_in_urls_locations_or_templates(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        page = client.get("/library")
        assert page.status_code == 200
        assert "?csrf_token=" not in page.text
        assert 'name="csrf-token"' in page.text  # meta for JavaScript

        created = client.post(
            "/projects",
            data={"csrf_token": "test-csrf", "name": "Location check"},
            follow_redirects=False,
        )
        assert created.status_code == 303
        assert "csrf_token" not in created.headers["location"]

        item_page = client.get(f"/items/{item.id}")
        assert "?csrf_token=" not in item_page.text
    finally:
        app.dependency_overrides.clear()


def test_rendered_forms_carry_the_hidden_token_field(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        page = client.get(f"/items/{item.id}")
        assert page.status_code == 200
        assert '<input type="hidden" name="csrf_token" value="test-csrf">' in page.text
    finally:
        app.dependency_overrides.clear()


def test_templates_never_render_a_query_token(tmp_path):
    """Structural sweep: no template action may embed ?csrf_token=."""
    from quirebase.web.templates import PACKAGE_DIR

    offenders = []
    for template in (PACKAGE_DIR / "templates").glob("*.html"):
        content = template.read_text(encoding="utf-8")
        if "?csrf_token=" in content:
            offenders.append(template.name)
    assert offenders == []
