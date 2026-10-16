from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from item_helpers import metadata_list_values
from sqlalchemy import select
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.accounts import update_user_status
from quirebase.core.config import Settings
from quirebase.core.errors import (
    PermissionDenied,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.library import create_item
from quirebase.library.tag_recommendations import recommend_item_tags
from quirebase.library.workflows import (
    commit_item_tag_recommendation_step,
    request_item_tag_recommendation,
)
from quirebase.models import Item, ItemTagRecommendation, User, WorkspaceMember, WorkspaceRole
from quirebase.workspaces import (
    archive_workspace,
    freeze_workspace_governance,
    set_workspace_member_role,
    terminate_workspace_member,
)


async def _user(db, username: str) -> User:
    user = User(username=username, password_hash="hash")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.anyio
async def test_request_is_idempotent_until_explicitly_superseded(async_db, fake_durable_operations):
    db = async_db
    user = await _user(db, "recommend-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Graph representation learning for molecules",
            "description": "A robust neural method for molecular prediction.",
            "subjects": [{"subject": v} for v in metadata_list_values("provider supplied keyword")],
        },
    )
    db.add(item)
    await db.flush()
    first = await request_item_tag_recommendation(
        db, item.id, workspace_id=fixture_workspace_id(user), actor_id=user.id
    )
    first_workflow_id = first.workflow_id
    item.keywords = metadata_list_values("entirely different upstream keywords")
    second = await request_item_tag_recommendation(
        db, item.id, workspace_id=fixture_workspace_id(user), actor_id=user.id
    )

    assert second.id == first.id
    assert second.generation_token == 1
    assert second.workflow_id == first_workflow_id
    assert fake_durable_operations.enqueues[-1]["queue_name"] == "library.recommendation"


@pytest.mark.anyio
async def test_item_creation_enqueues_and_worker_persists_yake_results(async_db, monkeypatch):
    db = async_db
    user = await _user(db, "automatic-owner")
    settings = Settings(_env_file=None, recommendation_engine="yake")
    monkeypatch.setattr("quirebase.library.tag_recommendations.get_settings", lambda: settings)

    item_result = await create_item(
        db,
        user,
        fixture_workspace_id(user),
        {
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Graph neural networks for molecular property prediction",
            "description": "Graph neural networks learn molecular representations and improve property prediction with robust message passing methods.",
        },
    )
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_result.item_id)
    )
    assert record is not None
    assert record.workflow_id is not None
    candidates = await recommend_item_tags(db, item_result.item_id, settings=settings)
    await commit_item_tag_recommendation_step(
        user.id,
        fixture_workspace_id(user),
        item_result.item_id,
        record.generation_token,
        record.workflow_id,
        candidates,
    )

    await db.refresh(record)
    assert record.generated_at is not None
    assert len(record.single_words or []) <= 10
    assert len(record.phrases or []) <= 10


@pytest.mark.anyio
async def test_stale_job_cannot_overwrite_new_generation(async_db):
    db = async_db
    user = await _user(db, "stale-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Stable title",
            "description": "Enough English content",
        },
    )
    db.add(item)
    await db.flush()
    settings = Settings(_env_file=None, recommendation_engine="yake")
    first = await request_item_tag_recommendation(
        db, item.id, workspace_id=fixture_workspace_id(user), actor_id=user.id
    )
    assert first.workflow_id is not None
    await request_item_tag_recommendation(
        db,
        item.id,
        workspace_id=fixture_workspace_id(user),
        actor_id=user.id,
        force=True,
    )
    await db.commit()

    candidates = await recommend_item_tags(db, item.id, settings=settings)
    result = await commit_item_tag_recommendation_step(
        user.id,
        fixture_workspace_id(user),
        item.id,
        1,
        first.workflow_id,
        candidates,
    )

    current = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    assert current is not None
    assert result == {"stale": True}
    assert current.generation_token == 2
    assert current.single_words is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("revocation", "denied_error"),
    [
        ("membership_terminated", WorkspaceMembershipRequired),
        ("account_deactivated", WorkspaceMembershipRequired),
        ("workspace_archived", WorkspaceLifecycleError),
        ("workspace_frozen", WorkspaceLifecycleError),
        ("role_downgraded", PermissionDenied),
    ],
)
async def test_recommendation_finalizer_rechecks_current_authority(
    async_db, async_session_factory, revocation, denied_error
):
    owner = await _user(async_db, "recommendation-governor")
    owner.role = "administrator"
    actor = User(username="recommendation-editor", password_hash="unused")
    async_db.add(actor)
    await async_db.flush()
    workspace_id = fixture_workspace_id(owner)
    membership = WorkspaceMember(
        workspace_id=workspace_id, user_id=actor.id, role=WorkspaceRole.editor
    )
    item = Item(
        workspace_id=workspace_id,
        created_by=owner.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Queued recommendation"},
    )
    async_db.add_all([membership, item])
    await async_db.flush()
    record = await request_item_tag_recommendation(
        async_db, item.id, workspace_id=workspace_id, actor_id=actor.id
    )
    await async_db.commit()
    actor_id, owner_id, item_id, membership_id, record_id = (
        actor.id,
        owner.id,
        item.id,
        membership.id,
        record.id,
    )
    generation_token, workflow_id = record.generation_token, record.workflow_id
    assert workflow_id is not None

    # Governance commits after the authorized request, before its result is published.
    async with async_session_factory() as governance_db:
        governor = await governance_db.get(User, owner_id)
        if revocation == "membership_terminated":
            await terminate_workspace_member(governance_db, governor, workspace_id, membership_id)
        elif revocation == "account_deactivated":
            await update_user_status(governance_db, governor, actor_id, False)
        elif revocation == "workspace_archived":
            await archive_workspace(governance_db, governor, workspace_id)
        elif revocation == "workspace_frozen":
            await freeze_workspace_governance(governance_db, governor, workspace_id)
        else:
            await set_workspace_member_role(
                governance_db, governor, workspace_id, membership_id, WorkspaceRole.viewer
            )

    with pytest.raises(denied_error):
        await commit_item_tag_recommendation_step(
            actor_id,
            workspace_id,
            item_id,
            generation_token,
            workflow_id,
            {"single_words": ["unauthorized"], "phrases": ["revoked result"]},
        )

    async with async_session_factory() as verification_db:
        current = await verification_db.get(ItemTagRecommendation, record_id)
        assert current is not None
        assert current.generation_token == generation_token
        assert current.workflow_id == workflow_id
        assert current.generated_at is None
        assert current.single_words is None
        assert current.phrases is None


@pytest.mark.anyio
async def test_concurrent_force_requests_receive_distinct_generation_tokens(
    async_db, async_session_factory
):
    db = async_db
    user = await _user(db, "concurrent-recommend-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Concurrent recommendation requests",
        },
    )
    db.add(item)
    await db.flush()
    await request_item_tag_recommendation(
        db, item.id, workspace_id=fixture_workspace_id(user), actor_id=user.id
    )
    await db.commit()
    user_id, item_id = user.id, item.id
    original_updated_at = item.updated_at

    start = asyncio.Barrier(2)

    async def force_request() -> tuple[int, str]:
        async with async_session_factory() as worker_db:
            await start.wait()
            record = await request_item_tag_recommendation(
                worker_db,
                item_id,
                workspace_id=fixture_workspace_id(user),
                actor_id=user_id,
                force=True,
            )
            await worker_db.commit()
            assert record.workflow_id is not None
            return record.generation_token, record.workflow_id

    results = await asyncio.gather(force_request(), force_request())

    if db.get_bind().dialect.name == "postgresql":
        assert {token for token, _job_id in results} == {2, 3}
        assert len({workflow_id for _token, workflow_id in results}) == 2
    else:
        # SQLite is a single-process development profile and intentionally
        # does not promise concurrent request serialization.
        assert all(token in {2, 3} for token, _job_id in results)
    await db.refresh(item)
    assert item.updated_at.replace(tzinfo=original_updated_at.tzinfo) == original_updated_at


@pytest.mark.anyio
async def test_missing_keybert_configuration_fails_explicitly(async_db):
    db = async_db
    user = await _user(db, "keybert-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Local semantic extraction",
        },
    )
    db.add(item)
    await db.flush()
    settings = Settings(
        _env_file=None,
        recommendation_engine="keybert",
        keybert_model_path=None,
    )
    record = await request_item_tag_recommendation(
        db, item.id, workspace_id=fixture_workspace_id(user), actor_id=user.id
    )
    assert record.workflow_id is not None

    with pytest.raises(RuntimeError, match="KEYBERT_MODEL_PATH"):
        await recommend_item_tags(db, item.id, settings=settings)


@pytest.mark.anyio
async def test_generation_result_does_not_include_source_text(async_db, monkeypatch):
    from types import SimpleNamespace

    from quirebase.models import FileRevision, FileRevisionProcessingState

    db = async_db
    user = await _user(db, "compact-generation-owner")
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Compact checkpoint"},
    )
    db.add(item)
    await db.flush()
    db.add(
        FileRevision(
            workspace_id=fixture_workspace_id(user),
            item_id=item.id,
            full_text="checkpoint sentinel " * 20_000,
            processing_state=FileRevisionProcessingState.ready,
            created_by=user.id,
            file=FileObject(
                backend="documents",
                filename="aa/bb/full-text.pdf",
                size=1,
                content_type="application/pdf",
                metadata={"original_name": "full-text.pdf"},
            ),
        )
    )
    settings = Settings(
        _env_file=None,
        recommendation_engine="yake",
        recommendation_max_chars=200_000,
    )

    class Engine:
        def recommend(self, _documents, _limits):
            return (SimpleNamespace(single_words=("compact",), phrases=("compact result",)),)

    monkeypatch.setattr("quirebase.library.tag_recommendations._engine", lambda _settings: Engine())
    candidates = await recommend_item_tags(db, item.id, settings=settings)

    assert candidates == {"single_words": ["compact"], "phrases": ["compact result"]}
