from __future__ import annotations

import json

import pytest

from quirebase.core.errors import PermissionDenied
from quirebase.library.imports import commit_import_batch
from quirebase.models import ImportBatch, Item, Project, ProjectMember, ProjectRole, User
from quirebase.projects.lifecycle import leave_project


@pytest.mark.anyio
async def test_import_confirmation_replays_the_committed_item_ids(async_db):
    user = User(username="batch-owner", password_hash="hash")
    async_db.add(user)
    await async_db.flush()
    batch = ImportBatch(
        owner_id=user.id,
        file_format="bibtex",
        records=json.dumps([{"title": "Replayable import", "authors": None}]),
        errors="[]",
    )
    async_db.add(batch)
    await async_db.commit()

    first = await commit_import_batch(async_db, user, batch.id)
    second = await commit_import_batch(async_db, user, batch.id)

    assert first == second
    assert len(first) == 1
    stored = await async_db.get(ImportBatch, batch.id)
    assert stored is not None and stored.status == "committed"
    assert await async_db.get(Item, first[0]) is not None


@pytest.mark.anyio
async def test_project_owner_cannot_leave_without_transfer(async_db):
    owner = User(username="project-owner", password_hash="hash")
    async_db.add(owner)
    await async_db.flush()
    project = Project(name="Owned", created_by=owner.id)
    async_db.add(project)
    await async_db.flush()
    async_db.add(ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.owner))
    await async_db.commit()

    with pytest.raises(PermissionDenied, match="transfer ownership"):
        await leave_project(async_db, owner, project.id)
