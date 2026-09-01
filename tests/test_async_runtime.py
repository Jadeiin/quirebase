from __future__ import annotations

import asyncio

import httpx2
import pytest
from inquiro import CandidatePage
from sqlalchemy import func, select

from quirebase.accounts import create_api_token
from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.library import DiscoveryClause, search_candidate_records
from quirebase.models import AuditEvent, User
from quirebase.web.app import create_app

pytestmark = pytest.mark.anyio


async def test_provider_wait_releases_the_read_transaction_and_other_request_progresses(
    async_session_factory,
    monkeypatch,
):
    async with async_session_factory() as seed_db:
        user = User(username="async-provider-user", password_hash="unused")
        seed_db.add(user)
        await seed_db.commit()
        user_id = user.id

    slow_started = asyncio.Event()
    release_slow = asyncio.Event()

    async def search_candidates(query, _settings):
        if query.clauses[0].term == "slow":
            slow_started.set()
            await release_slow.wait()
        return CandidatePage(query.provider, (), 0, query.page, query.per_page)

    monkeypatch.setattr("quirebase.library.discovery.search_candidates", search_candidates)
    settings = get_settings()
    async with (
        async_session_factory() as slow_db,
        async_session_factory() as fast_db,
    ):
        slow_user = await slow_db.get(User, user_id)
        fast_user = await fast_db.get(User, user_id)
        assert slow_user is not None and fast_user is not None
        slow = asyncio.create_task(
            search_candidate_records(
                slow_db,
                slow_user,
                "crossref",
                (DiscoveryClause("any", "and", "slow"),),
                settings=settings,
            )
        )
        await slow_started.wait()
        try:
            fast = await search_candidate_records(
                fast_db,
                fast_user,
                "crossref",
                (DiscoveryClause("any", "and", "fast"),),
                settings=settings,
            )
            assert fast.results == ()
        finally:
            release_slow.set()
        await slow

    async with async_session_factory() as check_db:
        audit_count = await check_db.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "metadata.search")
        )
    assert audit_count == 2


async def test_http_api_and_database_share_the_asyncio_request_loop(async_session_factory):
    async with async_session_factory() as db:
        user = User(username="async-http-user", password_hash="unused")
        db.add(user)
        await db.commit()
        grant = await create_api_token(db, user, "Async HTTP", expires_in_days=30)

    app = create_app(mcp_session_factory=async_session_factory)

    async def override_db():
        async with async_session_factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    transport = httpx2.ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {grant.raw_token}"}
    async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post("/api/v1/items", headers=headers, json={"title": "Async Item"})
        listed = await client.get("/api/v1/items", headers=headers)

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["items"][0]["title_html"] == "Async Item"
