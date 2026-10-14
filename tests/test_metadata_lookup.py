from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from app_helpers import json_payload
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import CandidateRecord, Identifier
from item_helpers import stored_doi, work_identifier
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent, ImportBatch, Item, ItemTagRecommendation


@pytest.mark.anyio
async def test_online_preview_uses_existing_confirmed_import_flow(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = item.workspace_id
    record = CandidateRecord(
        provider="crossref",
        lookup_identifier=Identifier("doi", "10.1000/looked-up"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Looked-up paper",
            "description": "Remote metadata",
            "date_published": "2026",
            "contributors": (get_one_author({"name": "Doe, Jane"}),),
            "container": {"title": "Journal"},
            "identifiers": [work_identifier("doi", "10.1000/looked-up")],
        }),
    )
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate", AsyncMock(return_value=record)
    )
    try:
        preview = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/identifier",
            json=json_payload({"identifier": "10.1000/looked-up", "provider": "auto"}),
        )
        assert preview.status_code == 201
        assert "Looked-up paper" in preview.text
        assert (
            await db.scalar(select(Item).where(Item.work["title"].as_string() == "Looked-up paper"))
            is None
        )
        batch = await db.scalar(select(ImportBatch).where(ImportBatch.file_format == "metadata"))
        assert batch is not None
        batch_id = batch.id
        committed = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/{batch_id}/commit", json=json_payload({})
        )
        assert committed.status_code == 200
        imported = await db.scalar(
            select(Item).where(Item.work["title"].as_string() == "Looked-up paper")
        )
        assert imported is not None
        assert stored_doi(imported) == "10.1000/looked-up"
        recommendation = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == imported.id)
        )
        assert recommendation is not None
        assert recommendation.workflow_id is not None
        assert await db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.lookup"))
    finally:
        await client.aclose()
        get_settings.cache_clear()
