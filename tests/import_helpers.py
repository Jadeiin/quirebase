from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import pymupdf

from quirebase.core.workflows import durable_operations
from quirebase.documents.revisions import delete_unreferenced_objects
from quirebase.library import workflows as library_workflows
from quirebase.library.imports import (
    _pdf_import_inputs,
    extract_pdf_import_identifier,
    finalize_pdf_import_batch,
    lookup_pdf_import_candidates,
)

if TYPE_CHECKING:
    from quirebase.models import ImportBatch


def pdf_import_batch_data(pending_records: list[dict]) -> dict:
    from uuid import uuid4

    from advanced_alchemy.types import FileObject

    files = []
    records = []
    for index, pending in enumerate(pending_records, start=1):
        pdf = pending["_pdf"]
        source_id = pending.setdefault("_source_id", str(uuid4()))
        files.append(
            FileObject(
                backend="documents",
                filename=pdf["object_key"],
                content_type="application/pdf",
                size=pdf.get("size"),
                metadata={
                    "row": pending.get("_row", index),
                    "source_id": source_id,
                    "original_name": pdf.get("original_name", "source.pdf"),
                },
            )
        )
        records.append({key: value for key, value in pending.items() if key != "_pdf"})
    return {"staged_files": files, "records": records}


async def finish_pdf_import_preview(db, session_factory, batch: ImportBatch, monkeypatch) -> None:
    operations = durable_operations()
    enqueued = next(
        (
            entry
            for entry in reversed(getattr(operations, "enqueues", []))
            if entry.get("workflow_id") == batch.workflow_id
            and entry["workflow_name"] == "library.prepare_pdf_import"
        ),
        None,
    )
    pending = enqueued["args"][-1] if enqueued else _pdf_import_inputs(batch.staged_files)

    async def lookup(batch_id, candidates):
        async with session_factory() as worker_db:
            return await lookup_pdf_import_candidates(worker_db, batch_id, candidates)

    async def finalize(actor_id, workspace_id, batch_id, workflow_id, records, errors):
        async with session_factory() as worker_db:
            result = await finalize_pdf_import_batch(
                worker_db, actor_id, workspace_id, batch_id, workflow_id, records, errors
            )
            await worker_db.commit()
            return result

    async def cleanup(
        _workflow_name, _actor_id, _workspace_id, keys, ignore_workflow_id=None, **_options
    ):
        async with session_factory() as worker_db:
            await delete_unreferenced_objects(
                worker_db, keys, ignore_workflow_id=ignore_workflow_id
            )
        return f"cleanup:{batch.id}"

    monkeypatch.setattr(
        library_workflows, "extract_pdf_import_identifier_step", extract_pdf_import_identifier
    )
    monkeypatch.setattr(library_workflows, "lookup_pdf_import_candidates_step", lookup)
    monkeypatch.setattr(library_workflows, "finalize_pdf_import_batch_step", finalize)
    monkeypatch.setattr(library_workflows, "enqueue_child_workflow", cleanup)
    workflow_body = library_workflows.prepare_pdf_import_workflow.__wrapped__.__wrapped__
    await workflow_body(batch.actor_id, batch.workspace_id, batch.id, batch.workflow_id, pending)
    operations = durable_operations()
    workflow = await operations.get(batch.workflow_id)
    if workflow is not None and hasattr(operations, "workflows"):
        operations.workflows[batch.workflow_id] = replace(
            workflow, state="succeeded", raw_status="SUCCESS"
        )
    await db.refresh(batch)


def pdf_bytes() -> bytes:
    document = pymupdf.open()
    document.new_page()
    contents = document.tobytes()
    document.close()
    return contents


def published_pdf_bytes(doi: str = "10.1000/published") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), f"https://doi.org/{doi}")
    document.set_metadata({"subject": f"doi:{doi}"})
    contents = document.tobytes()
    document.close()
    return contents
