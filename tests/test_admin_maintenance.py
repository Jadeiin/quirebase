from __future__ import annotations

import json

import pytest
from item_helpers import create_item_record as create_item
from sqlalchemy import select

from quirebase.core.config import get_settings
from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable
from quirebase.models import AuditEvent, Job, User
from quirebase.pipeline import (
    dispatch_maintenance_job,
    enqueue_job,
    list_jobs_admin,
    retry_all_failed_jobs,
    run_job,
)


async def create_test_admin(db, username="admin_maint_test"):
    admin = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role="administrator",
        active=True,
    )
    db.add(admin)
    await db.commit()
    return admin


async def create_test_member(db, username="member_maint_test"):
    user = User(
        username=username,
        password_hash=hash_password("memberpass123456"),
        role="member",
        active=True,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_system_reindex_job_execution(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_1")
    await create_item(db, admin, title="Reindexed Item", authors="Author One")

    job = await enqueue_job(db, "system.reindex_all", {}, owner_id=admin.id)
    await db.commit()

    await run_job(db, job)
    assert job.state == "succeeded"
    assert job.result is not None
    result = json.loads(job.result)
    assert "reindexed_items" in result
    assert result["reindexed_items"] >= 1


@pytest.mark.anyio
async def test_system_check_objects_job_execution(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_2")

    job = await enqueue_job(db, "system.check_objects", {}, owner_id=admin.id)
    await db.commit()

    await run_job(db, job)
    assert job.state == "succeeded"
    assert job.result is not None
    result = json.loads(job.result)
    assert "checked_status" in result
    assert result["checked_status"] == "ok"


@pytest.mark.anyio
async def test_system_backup_job_execution(async_db, tmp_path, monkeypatch):
    db = async_db
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    admin = await create_test_admin(db, "admin_maint_backup")
    await create_item(db, admin, title="Backup Item")

    job = await enqueue_job(db, "system.backup", {}, owner_id=admin.id)
    await db.commit()

    await run_job(db, job)
    assert job.state == "succeeded"
    assert job.result is not None
    result = json.loads(job.result)
    assert "filename" in result
    backup_file = get_settings().export_dir / result["filename"]
    assert backup_file.is_file()
    assert backup_file.stat().st_size > 0


@pytest.mark.anyio
async def test_dispatch_maintenance_job_commits_and_records_audit(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_dispatch")
    job = await dispatch_maintenance_job(db, admin, "system.reindex_all")

    assert job.id is not None
    assert job.kind == "system.reindex_all"

    # Verifying it was committed into database
    fetched = await db.get(Job, job.id)
    assert fetched is not None

    # Verifying audit event
    audit = await db.scalar(select(AuditEvent).where(AuditEvent.target_id == job.id))
    assert audit is not None
    assert audit.action == "admin.maintenance.reindex_all"


@pytest.mark.anyio
async def test_retry_all_failed_jobs(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_3")

    j1 = await enqueue_job(db, "system.reindex_all", {}, owner_id=admin.id)
    j1.state = "failed"
    j1.error = "Simulated error"
    j1.attempts = 3

    j2 = await enqueue_job(db, "system.check_objects", {}, owner_id=admin.id)
    j2.state = "failed"
    j2.error = "Simulated error 2"
    j2.attempts = 3
    await db.commit()

    count = await retry_all_failed_jobs(db, admin)
    assert count == 2
    assert j1.state == "pending"
    assert j2.state == "pending"


@pytest.mark.anyio
async def test_non_admin_cannot_list_jobs(async_db):
    db = async_db
    member = await create_test_member(db, "member_maint_blocked1")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await list_jobs_admin(db, member)


@pytest.mark.anyio
async def test_non_admin_cannot_retry_jobs(async_db):
    db = async_db
    member = await create_test_member(db, "member_maint_blocked2")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await retry_all_failed_jobs(db, member)


@pytest.mark.anyio
async def test_list_jobs_admin_filters_kind_prefix_under_high_volume(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_vol")

    # Create 2 system jobs
    sys1 = await enqueue_job(db, "system.backup", {}, owner_id=admin.id)
    sys2 = await enqueue_job(db, "system.reindex_all", {}, owner_id=admin.id)

    # Create 25 newer non-system jobs
    for i in range(25):
        await enqueue_job(db, f"pdf.inspect_{i}", {}, owner_id=admin.id)
    await db.commit()

    # Query with kind_prefix='system.' with limit=20
    system_jobs = await list_jobs_admin(db, admin, kind_prefix="system.", limit=20)
    assert len(system_jobs) == 2
    assert {j.id for j in system_jobs} == {sys1.id, sys2.id}


@pytest.mark.anyio
async def test_list_jobs_admin_positional_limit_compatibility(async_db):
    db = async_db
    admin = await create_test_admin(db, "admin_maint_pos")
    for i in range(10):
        await enqueue_job(db, f"test.job_{i}", {}, owner_id=admin.id)
    await db.commit()

    # Legacy positional call: (db, admin, state, limit)
    jobs = await list_jobs_admin(db, admin, "", 5)
    assert len(jobs) == 5
