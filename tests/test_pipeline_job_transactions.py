from __future__ import annotations

import json
from io import BytesIO

import pymupdf
import pytest
from sqlalchemy import select
from test_http import authenticated_client
from test_library_ui import pdf_bytes

from quirebase.core.config import get_settings
from quirebase.core.storage import LocalObjectStore
from quirebase.documents.revisions import store_pdf_revision
from quirebase.models import FileRevision, Job, PdfAnnotation, PdfAnnotationSegment, User
from quirebase.pipeline.jobs import (
    get_job_handler,
    register_job_handler,
    run_job,
)


def test_job_failure_rolls_back_partial_revision_state(db, tmp_path, monkeypatch):
    _client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    user = db.get(User, item.created_by)

    revision = store_pdf_revision(
        db,
        user,
        item.id,
        BytesIO(pdf_bytes()),
        "sample.pdf",
    )
    job = db.scalar(
        select(Job).where(
            Job.kind == "pdf.inspect", Job.idempotency_key == f"pdf.inspect:{revision.id}"
        )
    )
    assert job is not None
    assert revision.processing_state == "pending"

    # Simulate thumbnail failure during processing
    monkeypatch.setattr(
        "quirebase.pipeline.jobs.create_thumbnail",
        lambda _src, _dst: (_ for _ in ()).throw(RuntimeError("Thumbnail generation crashed")),
    )

    run_job(db, job)

    # Verify database session state: revision processing_state was rolled back and is NOT "ready"
    updated_revision = db.get(FileRevision, revision.id)
    assert updated_revision.processing_state == "pending"

    # Verify job record state was saved with error and retry state
    updated_job = db.get(Job, job.id)
    assert updated_job.state == "pending"
    assert "Thumbnail generation crashed" in updated_job.error
    assert updated_job.lease_until is None


def test_current_pdf_annotation_export_uses_username_and_annotation_body(db, tmp_path, monkeypatch):
    _client, item, revision = authenticated_client(db, tmp_path, monkeypatch)
    user = db.get(User, item.created_by)
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
        source = BytesIO(document.tobytes())
    key, digest, size = LocalObjectStore().put_pdf(source=source, maximum=100_000)
    revision.object_key = key
    revision.sha256 = digest
    revision.size = size
    annotation = PdfAnnotation(
        file_revision_id=revision.id,
        author_id=user.id,
        kind="highlight",
        scope="private",
        color="green",
        body="Reviewer-facing annotation",
        selected_text="Selected source text",
    )
    annotation.segments = [
        PdfAnnotationSegment(
            page_index=0,
            ordinal=0,
            x1=20,
            y1=300,
            x2=100,
            y2=300,
            x3=20,
            y3=280,
            x4=100,
            y4=280,
        )
    ]
    job = Job(
        kind="pdf.export_annotations",
        payload=json.dumps({
            "revision_id": revision.id,
            "project_id": None,
            "include_private": True,
        }),
        idempotency_key="pdf-export-username-and-body",
        owner_id=user.id,
    )
    db.add_all([annotation, job])
    db.commit()

    run_job(db, job)

    result = json.loads(job.result)
    with pymupdf.open(get_settings().export_dir / result["filename"]) as document:
        page = document[0]
        exported = next(page.annots())
        assert exported.info["title"] == user.username
        assert exported.info["content"] == "Reviewer-facing annotation"


def test_custom_job_handler_registry(db, tmp_path, monkeypatch):
    called = []

    def custom_handler(session, job, payload):
        called.append(payload.get("data"))
        return {"processed": True}

    register_job_handler("custom.test_job", custom_handler)
    assert get_job_handler("custom.test_job") is custom_handler

    user = User(
        username="handler_user",
        password_hash="test-hash",
        role="member",
    )
    db.add(user)
    db.flush()

    test_job = Job(
        kind="custom.test_job",
        payload=json.dumps({"data": "test_value"}),
        idempotency_key="custom:1",
        owner_id=user.id,
    )
    db.add(test_job)
    db.commit()

    run_job(db, test_job)
    assert called == ["test_value"]
    assert test_job.state == "succeeded"
    assert json.loads(test_job.result) == {"processed": True}


def test_job_registry_rejects_duplicate_handlers():
    def first_handler(session, job, payload):
        return {}

    register_job_handler("custom.duplicate", first_handler)
    with pytest.raises(ValueError, match="already registered"):
        register_job_handler("custom.duplicate", first_handler)


def test_invalid_job_payload_records_failure(db):
    user = User(username="invalid_payload_user", password_hash="test-hash", role="member")
    db.add(user)
    db.flush()
    job = Job(
        kind="pdf.inspect",
        payload="not-json",
        idempotency_key="invalid-payload:1",
        owner_id=user.id,
        attempts=1,
        state="running",
    )
    db.add(job)
    db.commit()

    run_job(db, job)

    db.refresh(job)
    assert job.state == "pending"
    assert "JSONDecodeError" in job.error
    assert job.lease_until is None
