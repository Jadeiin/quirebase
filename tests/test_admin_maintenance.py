from __future__ import annotations

import pytest
from sqlalchemy import select

from quirebase.core.crypto import hash_password
from quirebase.core.errors import ResourceUnavailable, ValidationFailure
from quirebase.models import AuditEvent, User
from quirebase.operations.workflows import dispatch_maintenance_workflow


async def create_user(db, username: str, role: str) -> User:
    user = User(
        username=username,
        password_hash=hash_password("adminpass123456"),
        role=role,
        active=True,
    )
    db.add(user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_dispatch_maintenance_workflow_is_transactional_and_audited(
    async_db, fake_durable_operations
):
    admin = await create_user(async_db, "maintenance-admin", "administrator")
    workflow_id = await dispatch_maintenance_workflow(async_db, admin, "reindex_all")
    workflow = await fake_durable_operations.get(workflow_id)
    assert workflow is not None
    assert workflow.name == "operations.reindex_all"
    assert workflow.queue_name == "operations"
    audit = await async_db.scalar(select(AuditEvent).where(AuditEvent.target_id == workflow_id))
    assert audit is not None
    assert audit.action == "admin.maintenance.reindex_all"


@pytest.mark.anyio
async def test_all_supported_maintenance_operations_use_the_global_queue(
    async_db, fake_durable_operations
):
    admin = await create_user(async_db, "maintenance-kinds", "administrator")
    for operation in ("reindex_all", "check_objects", "backup", "recommend_tags_all"):
        workflow_id = await dispatch_maintenance_workflow(async_db, admin, operation)
        workflow = await fake_durable_operations.get(workflow_id)
        assert workflow is not None
        assert workflow.queue_name == "operations"
        assert workflow.attributes == {
            "capability": "operations",
            "operation": operation,
            "owner_id": admin.id,
        }


@pytest.mark.anyio
async def test_non_admin_cannot_dispatch_maintenance(async_db):
    member = await create_user(async_db, "maintenance-member", "member")
    with pytest.raises(ResourceUnavailable, match="administrator required"):
        await dispatch_maintenance_workflow(async_db, member, "backup")


@pytest.mark.anyio
async def test_unknown_maintenance_operation_is_rejected(async_db):
    admin = await create_user(async_db, "maintenance-invalid", "administrator")
    with pytest.raises(ValidationFailure, match="unknown maintenance operation"):
        await dispatch_maintenance_workflow(async_db, admin, "retry_jobs")
