from unittest.mock import AsyncMock

import pytest
from inquiro import CandidateRecord, Identifier
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent, ImportBatch, Item, ItemTagRecommendation, Job, JobState


@pytest.mark.anyio
async def test_online_preview_uses_existing_confirmed_import_flow(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, _item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    record = CandidateRecord(
        provider="crossref",
        identifier=Identifier("doi", "10.1/looked-up"),
        title="Looked-up paper",
        abstract="Remote metadata",
        authors="Doe, Jane",
        publication_date="2026",
        publication_title="Journal",
        doi="10.1/looked-up",
        identifiers=(Identifier("doi", "10.1/looked-up"),),
        reference_type="journal-article",
    )
    monkeypatch.setattr(
        "quirebase.library.imports.lookup_candidate",
        AsyncMock(return_value=record),
    )
    try:
        preview = await client.post(
            "/metadata/preview",
            data={"csrf_token": "test-csrf", "identifier": "10.1/looked-up", "provider": "auto"},
        )
        assert preview.status_code == 200
        assert "Looked-up paper" in preview.text
        assert await db.scalar(select(Item).where(Item.title == "Looked-up paper")) is None
        batch = await db.scalar(
            select(ImportBatch).where(ImportBatch.file_format == "metadata:doi")
        )
        assert batch is not None
        committed = await client.post(
            f"/bibliography/import/{batch.id}",
            follow_redirects=False,
            data={"csrf_token": "test-csrf"},
        )
        assert committed.status_code == 303
        imported = await db.scalar(select(Item).where(Item.title == "Looked-up paper"))
        assert imported is not None
        assert imported.doi == "10.1/looked-up"
        recommendation = await db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == imported.id)
        )
        assert recommendation is not None
        job = await db.get(Job, recommendation.job_id)
        assert job is not None
        assert job.state == JobState.pending
        assert await db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.lookup"))
    finally:
        await client.aclose()
        get_settings.cache_clear()
