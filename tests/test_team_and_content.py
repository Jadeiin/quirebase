from datetime import UTC, datetime

from test_http import authenticated_client

from quirebase.accounts.throttling import check_login_throttle, record_login_failure
from quirebase.core.config import get_settings
from quirebase.models import DiscussionMessage, ItemTag, LoginThrottle, Tag
from quirebase.web.app import app


def test_tags_discussion_and_search(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        tagged = client.post(
            f"/items/{item.id}/tags?csrf_token=test-csrf", data={"name": "Quantum Optics"}
        )
        assert tagged.status_code == 200
        assert db.query(Tag).count() == 1
        assert db.query(ItemTag).count() == 1
        assert item.title in client.get("/?q=optics").text

        posted = client.post(
            f"/items/{item.id}/discussion?csrf_token=test-csrf", data={"body": "Looks useful"}
        )
        assert posted.status_code == 200
        assert db.query(DiscussionMessage).one().body == "Looks useful"

        uploaded = client.post(
            f"/items/{item.id}/attachments?csrf_token=test-csrf",
            files={"attachment": ("notes.txt", b"supplement", "text/plain")},
        )
        assert uploaded.status_code == 200
        page = client.get(f"/items/{item.id}/files")
        assert "notes.txt" in page.text
        assert page.headers["x-content-type-options"] == "nosniff"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_durable_login_throttle(db):
    identity = "a" * 64
    for _ in range(5):
        record_login_failure(db, identity)
    row = db.get(LoginThrottle, identity)
    assert row.failures == 5
    assert row.window_started_at.replace(tzinfo=UTC) <= datetime.now(UTC)

    try:
        check_login_throttle(db, identity)
    except Exception as error:
        assert error.status_code == 429
    else:
        raise AssertionError("throttle did not reject the sixth attempt")
