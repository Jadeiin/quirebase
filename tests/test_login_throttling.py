from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from quirebase.accounts import throttling
from quirebase.accounts.throttling import (
    THROTTLE_WINDOW,
    LoginThrottled,
    check_login_throttle,
    clear_login_failures,
    record_login_failure,
)
from quirebase.models import LoginThrottle

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


@pytest.mark.parametrize("existing", [False, True])
async def test_failure_counter_refreshes_loaded_state_and_shares_caller_rollback(
    persistence_db, persistence_sessions, monkeypatch, existing
):
    identity = "a" * 64
    now = datetime(2026, 10, 8, tzinfo=UTC)
    if existing:
        persistence_db.add(LoginThrottle(identity_hash=identity, failures=2, window_started_at=now))
        await persistence_db.commit()
        loaded = await persistence_db.get(LoginThrottle, identity)
    monkeypatch.setattr(throttling, "datetime", SimpleNamespace(now=lambda _timezone: now))
    monkeypatch.setattr(persistence_db, "commit", AsyncMock(side_effect=persistence_db.flush))
    await record_login_failure(persistence_db, identity)
    row = await persistence_db.get(LoginThrottle, identity)
    assert row.failures == (3 if existing else 1)
    if existing:
        assert row is loaded
    async with persistence_sessions() as observer:
        persisted = await observer.get(LoginThrottle, identity)
        assert (persisted.failures if persisted else None) == (2 if existing else None)
    await persistence_db.rollback()
    async with persistence_sessions() as observer:
        persisted = await observer.get(LoginThrottle, identity)
        assert (persisted.failures if persisted else None) == (2 if existing else None)


@pytest.mark.parametrize("expire_with", ["failure", "check"])
async def test_failure_window_resets_and_still_enforces_the_limit(
    persistence_db, monkeypatch, expire_with
):
    identity = "b" * 64
    now = datetime(2026, 10, 8, tzinfo=UTC)
    monkeypatch.setattr(throttling, "datetime", SimpleNamespace(now=lambda _timezone: now))
    persistence_db.add(
        LoginThrottle(
            identity_hash=identity,
            failures=10,
            window_started_at=now - THROTTLE_WINDOW - timedelta(seconds=1),
        )
    )
    await persistence_db.commit()
    if expire_with == "check":
        await check_login_throttle(persistence_db, identity)
        assert await persistence_db.get(LoginThrottle, identity) is None
    await record_login_failure(persistence_db, identity)
    row = await persistence_db.get(LoginThrottle, identity)
    assert (row.failures, row.window_started_at) == (1, now)
    for _ in range(4):
        await check_login_throttle(persistence_db, identity)
        await record_login_failure(persistence_db, identity)
    with pytest.raises(LoginThrottled):
        await check_login_throttle(persistence_db, identity)
    await clear_login_failures(persistence_db, identity)
    assert await persistence_db.get(LoginThrottle, identity) is None
