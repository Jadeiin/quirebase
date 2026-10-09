from __future__ import annotations

import asyncio
import json

import pytest
from concurrency_helpers import PostgresRace
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def test_named_sessions_observe_real_blocking_across_commits(postgres_sessions, tmp_path):
    race = PostgresRace(postgres_sessions, node_id="blocking", evidence_dir=tmp_path)
    try:
        async with race.session("holder") as holder:
            holder_pid = await holder.scalar(text("SELECT pg_backend_pid()"))
            await holder.execute(text("SELECT pg_advisory_xact_lock(12345)"))

            async def compete():
                async with race.session("waiter") as waiter:
                    waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
                    await waiter.execute(text("SELECT pg_advisory_xact_lock(12345)"))
                    await waiter.commit()
                    assert await waiter.scalar(text("SELECT pg_backend_pid()")) == waiter_pid
                    return waiter_pid

            race.start("compete", compete())
            await race.wait_blocked("waiter", "holder")
            await holder.commit()
            assert await holder.scalar(text("SELECT pg_backend_pid()")) == holder_pid
            assert await race.join("compete") != holder_pid
    finally:
        await race.close()


async def test_deadlock_records_sqlstate_and_preserves_first_failure(postgres_sessions, tmp_path):
    race = PostgresRace(postgres_sessions, node_id="deadlock", evidence_dir=tmp_path)
    ready = {name: asyncio.Event() for name in ("left", "right")}
    proceed = {name: asyncio.Event() for name in ready}

    async def contend(name, own_lock, other_lock):
        async with race.session(name) as db:
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": own_lock})
            ready[name].set()
            await proceed[name].wait()
            await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": other_lock})
            await db.commit()

    try:
        race.start("left", contend("left", 12347, 12348))
        race.start("right", contend("right", 12348, 12347))
        await asyncio.wait_for(
            asyncio.gather(*(event.wait() for event in ready.values())), timeout=5
        )
        proceed["left"].set()
        await race.wait_blocked("left", "right")
        proceed["right"].set()
        results = await asyncio.gather(
            race.join("left"), race.join("right"), return_exceptions=True
        )
        errors = [result for result in results if isinstance(result, DBAPIError)]
        assert len(errors) == 1 and errors[0].orig.sqlstate == "40P01"
        assert results.count(None) == 1
        await race.capture(AssertionError("later teardown must not hide the original SQLSTATE"))
        evidence = json.loads(race.evidence_path.read_text())
        assert evidence["failure"]["sqlstate"] == "40P01"
        assert any(row["action"] == "blocked" for row in evidence["trace"])
    finally:
        await race.close(failed=True)


async def test_timeout_captures_wait_graph_before_cancelling_tasks(postgres_sessions, tmp_path):
    race = PostgresRace(postgres_sessions, node_id="timeout", evidence_dir=tmp_path)
    try:
        async with race.session("holder") as holder:
            await holder.execute(text("SELECT pg_advisory_xact_lock(12346)"))

            async def compete():
                async with race.session("waiter") as waiter:
                    await waiter.execute(text("SELECT pg_advisory_xact_lock(12346)"))

            race.start("compete", compete())
            await race.wait_blocked("waiter", "holder")
            with pytest.raises(TimeoutError):
                await race.join("compete", wait_seconds=0.05)
            evidence = json.loads(race.evidence_path.read_text())
            waiting = next(
                row for row in evidence["snapshot"]["activity"] if row["pid"] == race.pids["waiter"]
            )
            assert race.pids["holder"] in waiting["blockers"]
            assert any(not lock["granted"] for lock in evidence["snapshot"]["locks"])
            assert evidence["failure"]["type"] == "TimeoutError"
            await race.close()
            await holder.commit()
        async with postgres_sessions() as db:
            assert await db.scalar(text("SELECT pg_try_advisory_xact_lock(12346)"))
    finally:
        await race.close(failed=True)


async def test_pytest_failure_captures_evidence_before_session_cleanup(postgres_sessions, tmp_path):
    race = PostgresRace(postgres_sessions, node_id="assertion", evidence_dir=tmp_path)
    secret = "do-not-log-bound-values"

    async def fail():
        async with race.session("actor") as db:
            assert await db.scalar(text("SELECT CAST(:value AS text)"), {"value": secret}) == secret
            pytest.fail("invariant failed")

    try:
        with pytest.raises(pytest.fail.Exception):
            await fail()
        evidence = json.loads(race.evidence_path.read_text())
        assert evidence["snapshot"]["activity"][0]["state"] == "idle in transaction"
        assert evidence["failure"]["type"] == "Failed"
        assert any(row["action"] == "transaction.begin" for row in evidence["trace"])
        assert any(row["action"] == "transaction.commit" for row in evidence["trace"])
        assert secret not in race.evidence_path.read_text()
    finally:
        await race.close()
