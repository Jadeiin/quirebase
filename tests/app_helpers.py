from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import httpx2
from advanced_alchemy.types import FileObject
from advanced_alchemy.utils.serialization import decode_json, encode_json
from starlette.routing import Router
from storage_helpers import put_pdf_object
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.models import FileRevision, Item, LoginSession, User
from quirebase.web.app import create_app


def _empty_mcp_mount(*_args, **_kwargs):
    @asynccontextmanager
    async def lifespan():
        yield

    return SimpleNamespace(server=None, app=Router(), lifespan=lifespan)


def create_web_test_app(**kwargs):
    """Build the HTTP adapter without regenerating the separately tested MCP projection."""
    with patch("quirebase.web.app.create_mcp_http_mount", _empty_mcp_mount):
        return create_app(**kwargs)


def json_payload(value):
    """Serialize domain UUIDs as actual HTTP JSON strings."""
    return decode_json(encode_json(value))


async def authenticated_async_client(db, session_factory, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    user = User(username="reader", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    raw = "test-session-token"
    login = LoginSession(
        token_hash=token_hash(raw),
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Paper"},
    )
    db.add_all([login, item])
    await db.flush()
    key, size = await put_pdf_object(b"%PDF-1.4\ntest", 100)
    revision = FileRevision(
        workspace_id=fixture_workspace_id(user),
        item_id=item.id,
        page_count=1,
        page_geometry=[[0, 0, 300, 400]],
        processing_state="ready",
        created_by=user.id,
        file=FileObject(
            backend="documents",
            filename=key,
            size=size,
            content_type="application/pdf",
            metadata={"original_name": "paper.pdf"},
        ),
    )
    db.add(revision)
    await db.commit()
    test_app = create_web_test_app(mcp_session_factory=session_factory)

    async def override_db():
        await asyncio.sleep(0)
        yield db

    test_app.dependency_overrides[get_db] = override_db
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=test_app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={"Accept-Language": "zh-CN,zh;q=0.9", "Origin": "http://testserver"},
        follow_redirects=True,
    )
    client.cookies.set(get_settings().session_cookie, raw)
    return (client, item, revision)


@asynccontextmanager
async def api_client(factory):
    app = create_web_test_app(mcp_session_factory=factory)

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
