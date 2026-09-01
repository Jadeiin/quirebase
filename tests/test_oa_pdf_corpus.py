from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pymupdf
import pytest
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.models import FileRevision, Job
from quirebase.pipeline import create_thumbnail, inspect_pdf, run_job, validate_pdf_container

CORPUS = json.loads((Path(__file__).parent / "oa_corpus.json").read_text(encoding="utf-8"))
PAPERS = CORPUS["papers"]


def corpus_directory() -> Path:
    configured = os.getenv("QUIREBASE_OA_PDF_DIR")
    return (
        Path(configured).resolve()
        if configured
        else Path(__file__).parents[1] / ".cache" / "oa-pdfs"
    )


def paper_path(paper: dict) -> Path:
    path = corpus_directory() / f"{paper['id']}.pdf"
    if not path.is_file():
        pytest.skip("run `uv run python scripts/download-oa-corpus.py` to enable OA PDF tests")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == paper["sha256"], f"OA fixture changed: {path}"
    return path


@pytest.mark.oa
@pytest.mark.parametrize("paper", PAPERS, ids=lambda paper: paper["id"])
def test_real_oa_pdf_service_pipeline(paper, tmp_path):
    source = paper_path(paper)
    thumbnail = tmp_path / f"{paper['id']}.png"

    validate_pdf_container(source)
    pages, text, geometry = inspect_pdf(source)
    create_thumbnail(source, thumbnail)

    assert pages == paper["pages"]
    assert len(text) >= paper["minimum_text_characters"]
    assert paper["search_phrase"].casefold() in text.casefold()
    assert len(geometry) == pages
    assert all(right > left and top > bottom for left, bottom, right, top in geometry)
    assert thumbnail.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    with pymupdf.open(source) as document:
        for page in document:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(0.2, 0.2), alpha=False)
            assert pixmap.width > 0 and pixmap.height > 0
            assert len(pixmap.samples) == pixmap.width * pixmap.height * pixmap.n


@pytest.mark.oa
@pytest.mark.parametrize("paper", PAPERS, ids=lambda paper: paper["id"])
@pytest.mark.anyio
async def test_real_oa_pdf_web_worker_search_annotation_export(
    paper, async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    source = paper_path(paper)
    client, item, _placeholder = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        with source.open("rb") as stream:
            uploaded = await client.post(
                f"/items/{item.id}/pdf",
                data={"csrf_token": "test-csrf"},
                files={"pdf": (source.name, stream, "application/pdf")},
                follow_redirects=False,
            )
        assert uploaded.status_code == 303
        revision = await db.scalar(
            select(FileRevision).where(
                FileRevision.item_id == item.id, FileRevision.original_name == source.name
            )
        )
        assert revision is not None
        job = await db.scalar(
            select(Job).where(Job.idempotency_key == f"pdf.inspect:{revision.id}")
        )
        assert job is not None
        await run_job(db, job)
        await db.refresh(revision)
        await db.refresh(job)
        assert job.state == "succeeded", job.error
        assert revision.processing_state == "ready"
        assert revision.page_count == paper["pages"]
        assert paper["search_phrase"].casefold() in revision.full_text.casefold()
        assert item.title in (await client.get(f"/?q={paper['search_phrase']}")).text

        content = await client.get(
            f"/documents/{item.id}/revisions/{revision.id}/content",
            headers={"Range": "bytes=0-1023"},
        )
        assert content.status_code == 206
        assert len(content.content) == 1024
        assert content.content.startswith(b"%PDF-")
        assert content.headers["etag"] == f'"{paper["sha256"]}"'

        left, bottom, right, top = json.loads(revision.page_geometry)[0]
        x1, x2 = left + 20, min(left + 120, right - 5)
        y1, y2 = top - 20, max(top - 40, bottom + 5)
        created = await client.post(
            f"/documents/{item.id}/annotations",
            headers={"X-CSRF-Token": "test-csrf"},
            json={
                "revision_id": revision.id,
                "kind": "highlight",
                "scope": "private",
                "color": "green",
                "selected_text": paper["search_phrase"],
                "segments": [{"page_index": 0, "quad_points": [x1, y1, x2, y1, x1, y2, x2, y2]}],
            },
        )
        assert created.status_code == 201, created.text
        requested = await client.post(
            f"/documents/{item.id}/annotation-exports",
            headers={"X-CSRF-Token": "test-csrf"},
            json={"revision_id": revision.id, "include_private": True},
        )
        assert requested.status_code == 202
        export_job = await db.get(Job, requested.json()["id"])
        assert export_job is not None
        await run_job(db, export_job)
        exported = await client.get(f"/annotation-exports/{export_job.id}/content")
        assert exported.status_code == 200
        assert hashlib.sha256(source.read_bytes()).hexdigest() == paper["sha256"]
        document = pymupdf.open(stream=exported.content, filetype="pdf")
        try:
            assert "Highlight" in [annotation.type[1] for annotation in document[0].annots()]
            assert document.page_count == paper["pages"]
        finally:
            document.close()
    finally:
        await client.aclose()
        get_settings.cache_clear()
