import json
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi.testclient import TestClient

from quirebase.app import app
from quirebase.config import get_settings
from quirebase.db import get_db
from quirebase.models import AuditEvent, FileRevision, Item, LoginSession, User
from quirebase.security import token_hash
from quirebase.storage import LocalObjectStore


def authenticated_client(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    db.flush()
    raw = "test-session-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        csrf_token="test-csrf",
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(title="Paper", created_by=user.id)
    db.add_all([login, item])
    db.flush()
    key, digest, size = LocalObjectStore().put_pdf(
        source=BytesIO(b"%PDF-1.4\ntest"),
        maximum=100,
    )
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name="paper.pdf",
        page_count=1,
        page_geometry=json.dumps([[0, 0, 300, 400]]),
        processing_state="ready",
        created_by=user.id,
    )
    db.add(revision)
    db.commit()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    client.cookies.set(get_settings().session_cookie, raw)
    return client, item, revision


def test_pdf_range_and_annotation_api(db, tmp_path, monkeypatch):
    client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        content = client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-4"},
        )
        assert content.status_code == 206
        assert content.content == b"%PDF-"
        assert content.headers["content-range"].startswith("bytes 0-4/")

        created = client.post(
            f"/documents/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "revision_id": revision.id,
                "kind": "highlight",
                "scope": "private",
                "color": "yellow",
                "selected_text": "test",
                "segments": [
                    {
                        "page_index": 0,
                        "quad_points": [10, 20, 30, 20, 10, 10, 30, 10],
                    }
                ],
            },
        )
        assert created.status_code == 201
        annotation = created.json()
        assert annotation["mine"] is True

        conflict = client.patch(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"version": 99, "color": "red"},
        )
        assert conflict.status_code == 409

        deleted = client.delete(
            f"/documents/{item.id}/annotations/{annotation['id']}",
            headers={"X-CSRF-Token": "test-csrf"},
        )
        assert deleted.status_code == 204
        assert deleted.content == b""
        assert (
            db
            .query(AuditEvent)
            .filter_by(action="annotation.delete", target_id=annotation["id"])
            .one()
        )
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_edit_detects_conflicts_and_updates_search(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        updated = client.post(
            f"/items/{item.id}/edit?csrf_token=test-csrf",
            data={
                "version": 1,
                "title": "Revised Paper",
                "abstract": "Quantum transport",
            },
            follow_redirects=False,
        )
        assert updated.status_code == 303
        db.refresh(item)
        assert item.version == 2
        assert item.title == "Revised Paper"

        results = client.get("/?q=quantum")
        assert results.status_code == 200
        assert "Revised Paper" in results.text

        stale = client.post(
            f"/items/{item.id}/edit?csrf_token=test-csrf",
            data={"version": 1, "title": "Lost update"},
        )
        assert stale.status_code == 409
        db.refresh(item)
        assert item.title == "Revised Paper"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
