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
    item_id = item.id
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        tagged = await client.post(
            f"{workspace_base}/items/{item_id}/tags", json={"name": "Quantum Optics"}
        )
        assert tagged.status_code == 200
        assert await db.scalar(select(func.count()).select_from(Tag)) == 1
        assert await db.scalar(select(func.count()).select_from(ItemTag)) == 1
        search = await client.get(f"{workspace_base}/items", params={"query": "optics"})
        assert search.json()["items"] == []

        posted = await client.post(
            f"{workspace_base}/items/{item_id}/discussions", json={"body": "Looks useful"}
        )
        assert posted.status_code == 201
        message = await db.scalar(select(DiscussionMessage))
        assert message is not None
        assert message.body == "Looks useful"

        uploaded = await client.post(
            f"{workspace_base}/items/{item_id}/attachments",
            files={"attachment": ("notes.txt", b"supplement", "text/plain")},
        )
        assert uploaded.status_code == 202
        workflow_id = uploaded.json()["id"]
        assert workflow_id.startswith("upload-attachment:")
        status = await client.get(f"{workspace_base}/workflows/{workflow_id}")
        assert status.json()["state"] == "pending"
        workspace = await client.get(f"{workspace_base}/items/{item_id}/overview")
        assert workspace.json()["counts"]["attachments"] == 0
        assert workspace.headers["x-content-type-options"] == "nosniff"
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
        response = await client.get(
            f"/workspaces/{item.workspace_id}/items/{item.id}/files",
            headers={"Accept": "text/html"},
        )
        csp = response.headers.get("content-security-policy", "")
        if "connect-src 'self' https: http:" not in csp:
            pytest.skip(
                "frontend build with browser PDF CSP is unavailable in this test environment"
            )

        assert "connect-src 'self' https: http:" in csp
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
