from __future__ import annotations

import asyncio
import json

import pymupdf
import pytest
from sqlalchemy import select
from storage_helpers import put_pdf_object
from test_http import authenticated_async_client
from test_library_ui import pdf_bytes

from quirebase.core.storage import get_object_store
from quirebase.documents.revisions import store_pdf_revision
from quirebase.models import FileRevision, Job, PdfAnnotation, PdfAnnotationSegment, User
from quirebase.pipeline.jobs import (
    get_job_handler,
    register_job_handler,
    run_job,
)


@pytest.mark.anyio
async def test_job_failure_rolls_back_partial_revision_state(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    user = await db.get(User, item.created_by)
    assert user is not None

    revision = await store_pdf_revision(
        db,
        user,
        item.id,
        pdf_bytes(),
        "sample.pdf",
    )
    job = await db.scalar(
        select(Job).where(
            Job.kind == "pdf.inspect", Job.idempotency_key == f"pdf.inspect:{revision.id}"
        )
    )
    assert job is not None
    assert revision.processing_state == "pending"
    revision_id, job_id = revision.id, job.id

    # Simulate thumbnail failure during processing
    monkeypatch.setattr(
        "quirebase.pipeline.jobs.create_thumbnail",
        lambda _src, _dst: (_ for _ in ()).throw(RuntimeError("Thumbnail generation crashed")),
    )

    await run_job(db, job)

    # Verify database session state: revision processing_state was rolled back and is NOT "ready"
    updated_revision = await db.get(FileRevision, revision_id)
    assert updated_revision is not None
    assert updated_revision.processing_state == "pending"

    # Verify job record state was saved with error and retry state
    updated_job = await db.get(Job, job_id)
    assert updated_job is not None
    assert updated_job.state == "pending"
    assert "Thumbnail generation crashed" in updated_job.error
    assert updated_job.lease_until is None
    await client.aclose()


@pytest.mark.anyio
async def test_current_pdf_annotation_export_uses_username_and_annotation_body(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    user = await db.get(User, item.created_by)
    assert user is not None
    with pymupdf.open() as document:
        document.new_page(width=300, height=400)
        source = document.tobytes()
    key, digest, size = await put_pdf_object(source, 100_000)
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
    await db.commit()

    await run_job(db, job)

    result = json.loads(job.result)
    async with get_object_store().materialize(result["object_key"]) as path:
        with pymupdf.open(path) as document:
            page = document[0]
            exported = next(page.annots())
            assert exported.info["title"] == user.username
            assert exported.info["content"] == "Reviewer-facing annotation"
    await client.aclose()


@pytest.mark.anyio
async def test_custom_job_handler_registry(async_db, tmp_path, monkeypatch):
    db = async_db
    called = []

    async def custom_handler(session, job, payload):
        await asyncio.sleep(0)
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
    await db.flush()

    test_job = Job(
        kind="custom.test_job",
        payload=json.dumps({"data": "test_value"}),
        idempotency_key="custom:1",
        owner_id=user.id,
    )
    db.add(test_job)
    await db.commit()

    await run_job(db, test_job)
    assert called == ["test_value"]
    assert test_job.state == "succeeded"
    assert json.loads(test_job.result) == {"processed": True}


def test_job_registry_rejects_duplicate_handlers():
    async def first_handler(session, job, payload):
        await asyncio.sleep(0)
        return {}

    register_job_handler("custom.duplicate", first_handler)
    with pytest.raises(ValueError, match="already registered"):
        register_job_handler("custom.duplicate", first_handler)


@pytest.mark.anyio
async def test_invalid_job_payload_records_failure(async_db):
    db = async_db
    user = User(username="invalid_payload_user", password_hash="test-hash", role="member")
    db.add(user)
    await db.flush()
    job = Job(
        kind="pdf.inspect",
        payload="not-json",
        idempotency_key="invalid-payload:1",
        owner_id=user.id,
        attempts=1,
        state="running",
    )
    db.add(job)
    await db.commit()

    await run_job(db, job)

    await db.refresh(job)
    assert job.state == "pending"
    assert "JSONDecodeError" in job.error
    assert job.lease_until is None
