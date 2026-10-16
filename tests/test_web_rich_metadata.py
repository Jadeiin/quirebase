from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from app_helpers import json_payload
from commonmeta.base_utils import compact
from inquiro import CandidateRecord, Identifier
from item_helpers import contributor_values
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure
from quirebase.models import Item, ItemTag, ItemTagRecommendation, SystemSetting, Tag, User


@pytest.mark.anyio
async def test_citation_key_preview_is_an_authenticated_account_capability(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(
            "/api/v1/account/citation-key-preview", params={"formula": "auth + year"}
        )
        assert response.status_code == 200
        assert response.json()["key"]
        invalid = await client.get(
            "/api/v1/account/citation-key-preview", params={"formula": "broken("}
        )
        assert invalid.status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_http_api_tag_matrix_and_selection(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    item.work = {
        **item.work,
        "subjects": [
            {"subject": "Natural Language Processing"},
            {"subject": "New Research Direction"},
        ],
    }
    tag1 = Tag(workspace_id=item.workspace_id, name="Machine Learning", created_by=item.created_by)
    tag2 = Tag(workspace_id=item.workspace_id, name="Transformers", created_by=item.created_by)
    db.add_all([tag1, tag2])
    await db.flush()
    db.add(ItemTag(workspace_id=item.workspace_id, item_id=item.id, tag_id=tag2.id))
    recommendation = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    if recommendation is None:
        recommendation = ItemTagRecommendation(
            workspace_id=item.workspace_id, item_id=item.id, generation_token=1
        )
        db.add(recommendation)
    recommendation.single_words = []
    recommendation.phrases = ["Natural Language Processing", "New Research Direction"]
    recommendation.generated_at = datetime.now(UTC)
    await db.commit()
    organize = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert organize.status_code == 200
    assert organize.json()["tag_matrix"]["suggested_names"] == [
        "Natural Language Processing",
        "New Research Direction",
    ]
    response = await client.put(
        f"{workspace_base}/items/{item_id}/tags",
        json=json_payload({
            "add_tag_ids": [tag1.id],
            "remove_tag_ids": [tag2.id],
            "new_names": ["Natural Language Processing", "New Research Direction", "Deep Learning"],
        }),
    )
    assert response.status_code == 200
    organized = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert organized.status_code == 200
    matrix = organized.json()["tag_matrix"]
    selected_tags = {
        tag["name"]
        for group in matrix["groups"]
        for tag in group["tags"]
        if tag["id"] in matrix["assigned_ids"]
    }
    assert selected_tags == {
        "Machine Learning",
        "Natural Language Processing",
        "New Research Direction",
        "Deep Learning",
    }
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_tag_recommendation_pending_failed_and_retry_states(
    async_db, async_session_factory, tmp_path, monkeypatch, fake_durable_operations
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    workflow_id = f"recommendation-ui:{item.id}"
    await fake_durable_operations.enqueue(
        "library.recommend_tags",
        queue_name="library",
        workflow_id=workflow_id,
        attributes={"actor_id": item.created_by, "workspace_id": item.workspace_id},
    )
    recommendation = ItemTagRecommendation(
        workspace_id=item.workspace_id,
        item_id=item.id,
        generation_token=1,
        workflow_id=workflow_id,
        single_words=["stale-candidate"],
        phrases=[],
    )
    db.add(recommendation)
    await db.commit()
    pending = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert pending.json()["tag_matrix"]["recommendation_state"] == "pending"
    assert pending.json()["tag_matrix"]["suggested_names"] == []
    current = fake_durable_operations.workflows[workflow_id]
    fake_durable_operations.workflows[workflow_id] = replace(
        current, state="failed", raw_status="ERROR", error="RuntimeError: extraction failed"
    )
    failed = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert failed.json()["tag_matrix"]["recommendation_state"] == "failed"
    assert failed.json()["tag_matrix"]["recommendation_error"] == "RuntimeError: extraction failed"
    retry = await client.post(f"{workspace_base}/items/{item_id}/tag-recommendations")
    assert retry.status_code == 200
    retry_workflow_id = retry.json()["id"]
    assert retry_workflow_id == f"item-recommend-tags:{item_id}:2"
    progress = await client.get(f"{workspace_base}/workflows/{retry_workflow_id}")
    assert progress.json()["state"] == "pending"
    await db.refresh(recommendation)
    assert recommendation.generation_token == 2
    assert recommendation.generated_at is None
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_sync_metadata_uses_effective_runtime_provider_settings(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    db.add(SystemSetting(key="nasa_ads_token", value="runtime-ads-token"))
    await db.commit()
    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        new=AsyncMock(
            return_value=CandidateRecord(
                provider="nasa_ads",
                lookup_identifier=Identifier("bibcode", "2024ApJ...123A...1X"),
                work=compact({
                    "id": f"urn:uuid:{uuid4()}",
                    "type": "Document",
                    "title": "Runtime-configured metadata",
                }),
            )
        ),
    ) as lookup:
        response = await client.post(
            f"{workspace_base}/items/{item.id}/metadata/sync",
            json=json_payload({
                "expected_version": item.version,
                "provider": "bibcode",
                "uid": "2024ApJ...123A...1X",
            }),
        )
    assert response.status_code == 200
    assert lookup.call_args.args[2].nasa_ads_token == "runtime-ads-token"
    await client.aclose()


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ValidationFailure("identifier is malformed"), 422),
        (ResourceNotFound("metadata not found"), 404),
        (UpstreamServiceError("provider unavailable"), 502),
    ],
)
@pytest.mark.anyio
async def test_http_api_sync_metadata_translates_expected_lookup_failures(
    async_db, async_session_factory, tmp_path, monkeypatch, error, status_code
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    with patch("quirebase.library.identifiers.lookup_candidate", new=AsyncMock(side_effect=error)):
        response = await client.post(
            f"{workspace_base}/items/{item.id}/metadata/sync",
            json=json_payload({
                "expected_version": item.version,
                "provider": "doi",
                "uid": "invalid",
            }),
        )
    assert response.status_code == status_code
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_suggests_authors(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    other = User(username="author-suggestion-other", password_hash="unused")
    db.add(other)
    await db.flush()
    await provision_initial_workspace(db, other)
    other_item = Item(
        workspace_id=fixture_workspace_id(other),
        created_by=other.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "Other",
            "contributors": contributor_values("Leibniz, Gottfried"),
        },
    )
    db.add(other_item)
    item.work = {**item.work, "contributors": contributor_values("LeCun, Yann")}
    await db.commit()
    response = await client.get(f"{workspace_base}/authors?query=le")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["last_name"] == "LeCun"
    assert data[0]["first_name"] == "Yann"
    assert "id" not in data[0]
    forbidden = await client.get(
        f"/api/v1/workspaces/{fixture_workspace_id(other)}/authors?query=le"
    )
    assert forbidden.status_code == 404
    assert forbidden.json() == {"code": "workspace_unavailable", "message": "Workspace not found"}
    client.cookies.clear()
    assert (await client.get(f"{workspace_base}/authors?query=le")).status_code == 401
    await client.aclose()
