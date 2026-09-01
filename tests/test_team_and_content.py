from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from test_http import authenticated_async_client

from quirebase.accounts.throttling import check_login_throttle, record_login_failure
from quirebase.core.config import get_settings
from quirebase.models import DiscussionMessage, ItemTag, LoginThrottle, Tag


@pytest.mark.anyio
async def test_tags_discussion_and_search(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        tagged = await client.post(
            f"/items/{item.id}/tags", data={"csrf_token": "test-csrf", "name": "Quantum Optics"}
        )
        assert tagged.status_code == 200
        assert await db.scalar(select(func.count()).select_from(Tag)) == 1
        assert await db.scalar(select(func.count()).select_from(ItemTag)) == 1
        assert item.title in (await client.get("/?q=optics")).text

        posted = await client.post(
            f"/items/{item.id}/discussion", data={"csrf_token": "test-csrf", "body": "Looks useful"}
        )
        assert posted.status_code == 200
        message = await db.scalar(select(DiscussionMessage))
        assert message is not None
        assert message.body == "Looks useful"

        uploaded = await client.post(
            f"/items/{item.id}/attachments",
            data={"csrf_token": "test-csrf"},
            files={"attachment": ("notes.txt", b"supplement", "text/plain")},
        )
        assert uploaded.status_code == 200
        page = await client.get(f"/items/{item.id}/files")
        assert "notes.txt" in page.text
        assert page.headers["x-content-type-options"] == "nosniff"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_csp_allows_browser_pdf_downloads_from_external_http_sources(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(f"/items/{item.id}/files")

        assert "connect-src 'self' https: http:" in response.headers["content-security-policy"]
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_durable_login_throttle(async_db):
    db = async_db
    identity = "a" * 64
    for _ in range(5):
        await record_login_failure(db, identity)
    row = await db.get(LoginThrottle, identity)
    assert row is not None
    assert row.failures == 5
    assert row.window_started_at.replace(tzinfo=UTC) <= datetime.now(UTC)

    try:
        await check_login_throttle(db, identity)
    except Exception as error:
        assert error.status_code == 429
    else:
        raise AssertionError("throttle did not reject the sixth attempt")
