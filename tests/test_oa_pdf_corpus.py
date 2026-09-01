from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pymupdf
import pytest
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.documents.pdf import create_thumbnail, inspect_pdf, validate_pdf_container

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
    paper, async_db, async_session_factory, tmp_path, monkeypatch, fake_durable_operations
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
        workflow_id = uploaded.headers["location"].partition("workflow=")[2]
        workflow = await fake_durable_operations.get(workflow_id)
        assert workflow is not None
        assert workflow.name == "documents.upload_revision"
    finally:
        await client.aclose()
        get_settings.cache_clear()
