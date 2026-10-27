from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from advanced_alchemy.types import GUID
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from workspace_helpers import provision_initial_workspace

from quirebase.models import User


async def _assert_rejected(db, statement: str, parameters: dict[str, str | UUID]) -> None:
    query = text(statement).bindparams(
        *(
            bindparam(key, type_=GUID())
            for key, value in parameters.items()
            if isinstance(value, UUID)
        )
    )
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(query, parameters)


async def assert_closed_state_constraints(db) -> None:
    user = User(username="closed-states", password_hash="unused")
    db.add(user)
    await db.flush()
    workspace = await provision_initial_workspace(db, user)
    await db.commit()

    for state in ("unknown", "deleted"):
        await _assert_rejected(
            db,
            "UPDATE workspaces SET state = :state WHERE id = :id",
            {"state": state, "id": workspace.id},
        )
        await _assert_rejected(
            db,
            "INSERT INTO projects "
            "(id, workspace_id, name, description, created_by, state, participation, created_at, updated_at) "
            "VALUES (:id, :workspace_id, 'bad', '', :user_id, :state, 'workspace', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            {"id": uuid4(), "workspace_id": workspace.id, "user_id": user.id, "state": state},
        )
    await _assert_rejected(
        db,
        "INSERT INTO workspace_members "
        "(id, workspace_id, user_id, role, state, invited_by, created_at, updated_at) "
        "VALUES (:id, :workspace_id, :user_id, 'invalid', 'active', :user_id, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        {"id": uuid4(), "workspace_id": workspace.id, "user_id": user.id},
    )
