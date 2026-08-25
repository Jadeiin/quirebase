from inquiro import CandidateRecord, Identifier
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.models import AuditEvent, ImportBatch, Item, ItemTagRecommendation, Job, JobState
from quirebase.web.app import app


def test_online_preview_uses_existing_confirmed_import_flow(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
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
        lambda _value, _provider, _settings: record,
    )
    try:
        preview = client.post(
            "/metadata/preview?csrf_token=test-csrf",
            data={"identifier": "10.1/looked-up", "provider": "auto"},
        )
        assert preview.status_code == 200
        assert "Looked-up paper" in preview.text
        assert db.scalar(select(Item).where(Item.title == "Looked-up paper")) is None
        batch = db.scalar(select(ImportBatch).where(ImportBatch.file_format == "metadata:doi"))
        committed = client.post(
            f"/bibliography/import/{batch.id}?csrf_token=test-csrf", follow_redirects=False
        )
        assert committed.status_code == 303
        imported = db.scalar(select(Item).where(Item.title == "Looked-up paper"))
        assert imported.doi == "10.1/looked-up"
        recommendation = db.scalar(
            select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == imported.id)
        )
        assert recommendation is not None
        job = db.get(Job, recommendation.job_id)
        assert job is not None
        assert job.state == JobState.pending
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.lookup"))
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
