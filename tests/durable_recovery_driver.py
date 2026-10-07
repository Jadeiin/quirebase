"""Isolated-process driver for the real PDF import/recovery contract."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from pathlib import Path
from uuid import UUID

import pymupdf
from advanced_alchemy.types import FileObject
from inquiro.models import CandidateRecord, Identifier
from sqlalchemy import func, select, update
from workspace_helpers import provision_initial_workspace

from quirebase.cli import _register_workflows
from quirebase.core.database import AsyncSessionLocal, engine
from quirebase.core.errors import ResourceNotFound
from quirebase.core.storage import get_object_store
from quirebase.core.workflows import durable_operations, launch_worker, recover_workflows
from quirebase.library import (
    commit_import_batch,
    get_import_batch_preview,
    imports,
    stage_pdf_import_batch,
)
from quirebase.models import AuditEvent, FileRevision, ImportBatch, Item, User
from quirebase.search import search_index


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def instrument_external_provider(directory, *, pause):
    extract = imports.extract_pdf_import_doi

    async def observed_extract(pending):
        result = await extract(pending)
        with (directory / "extractions.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(pending["_pdf"]) + "\n")
        return result

    async def lookup(identifier, _identifier_type, _settings):
        if identifier.endswith("recovery-rejected"):
            if pause:
                (directory / "checkpoint-reached").touch()
                await asyncio.Event().wait()
            raise ResourceNotFound("no metadata for this PDF")
        return CandidateRecord(
            provider="crossref",
            identifier=Identifier("doi", identifier),
            title="Recovery retained paper",
            doi=identifier,
            authors="Recovery, Author",
        )

    imports.extract_pdf_import_doi = observed_extract
    imports.lookup_candidate = lookup


async def stage(directory):
    uploads = []
    for suffix in ("kept", "rejected"):
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), f"https://doi.org/10.1000/recovery-{suffix}")
            uploads.append((document.tobytes(), f"uploaded-{suffix}.pdf"))
    async with AsyncSessionLocal() as db:
        actor = User(username="recovery-owner", password_hash="unused")
        db.add(actor)
        await db.flush()
        workspace = await provision_initial_workspace(db, actor)
        await db.commit()
        batch, _, _ = await stage_pdf_import_batch(db, actor, workspace.id, uploads)
        write_json(
            directory / "state.json",
            {
                "actor_id": str(actor.id),
                "workspace_id": str(workspace.id),
                "batch_id": str(batch.id),
                "workflow_id": batch.workflow_id,
                "files": [file.to_dict() for file in batch.staged_files],
            },
        )


async def change_descriptor(state):
    async with AsyncSessionLocal() as db:
        batch = await db.get(ImportBatch, UUID(state["batch_id"]))
        files = [file.to_dict() for file in batch.staged_files]
        files[1]["metadata"]["original_name"] = "changed-after-checkpoint.pdf"
        await db.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch.id)
            .values(staged_files=[FileObject(**file) for file in files])
        )
        await db.commit()
        await db.refresh(batch)
        assert batch.staged_files[1].metadata["original_name"] == "changed-after-checkpoint.pdf"


async def confirm(directory, state, *, crash):
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, UUID(state["actor_id"]))
        ids = await commit_import_batch(
            db, actor, UUID(state["workspace_id"]), UUID(state["batch_id"])
        )
        if crash:
            # The commit is durable but the caller has received no response.
            (directory / "confirmation-committed").touch()
            await asyncio.Event().wait()
        write_json(directory / "confirmed.json", [str(item_id) for item_id in ids])


async def finish_cleanup(directory, state):
    worker = asyncio.create_task(launch_worker())
    try:
        async with asyncio.timeout(30):
            while True:
                status = await durable_operations().get(
                    f"prepare-pdf-import-cleanup:{state['workflow_id']}"
                )
                if status is not None and status.state == "succeeded":
                    break
                if worker.done():
                    await worker
                await asyncio.sleep(0.05)
        await inspect_contract(directory, state, committed=True)
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


async def inspect_contract(directory, state, *, committed):
    status = await durable_operations().get(state["workflow_id"])
    assert status.state == "succeeded"
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, UUID(state["actor_id"]))
        batch, records, diagnostics = await get_import_batch_preview(
            db, actor, UUID(state["workspace_id"]), UUID(state["batch_id"])
        )
        assert batch.status == ("committed" if committed else "ready")
        assert len(records) == 1 and records[0]["title"] == "Recovery retained paper"
        assert len(diagnostics) == 1
        assert diagnostics[0]["filename"] == "uploaded-rejected.pdf"
        assert diagnostics[0]["code"] == "metadata_not_found"
        events = list(await db.scalars(select(AuditEvent)))
        assert sum(event.action == "pdf.import.preview.request" for event in events) == 1
        assert sum(event.action == "pdf.import.preview" for event in events) == 1
        if not committed:
            assert len(batch.staged_files) == 1
            assert batch.staged_files[0].path == state["files"][0]["filename"]
            assert await db.scalar(select(func.count()).select_from(Item)) == 0
            return
        expected_ids = json.loads((directory / "confirmed.json").read_text(encoding="utf-8"))
        items = list(await db.scalars(select(Item)))
        revisions = list(await db.scalars(select(FileRevision)))
        assert [str(item.id) for item in items] == expected_ids == batch.committed_item_ids
        assert not batch.staged_files and len(revisions) == 1
        assert revisions[0].item_id == items[0].id
        assert revisions[0].file.path == state["files"][0]["filename"]
        assert sum(event.action == "pdf.import" for event in events) == 1
        hits = await search_index(db).search(db, "Recovery")
        assert set(hits) == {items[0].id}
        workflows = await durable_operations().list(limit=100)
        names = [row.name for row in workflows]
        assert names.count("library.prepare_pdf_import") == 1
        assert names.count("documents.cleanup_objects") == 1
        assert names.count("library.recommend_tags") == 1
        assert names.count("documents.inspect_imported_revision") == 1
    store = get_object_store()
    assert await store.exists(state["files"][0]["filename"])
    assert not await store.exists(state["files"][1]["filename"])


async def main(mode, directory):
    _register_workflows()
    get_object_store()
    if mode == "stage":
        await stage(directory)
        return
    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
    instrument_external_provider(directory, pause=mode == "worker")
    if mode == "worker":
        await launch_worker()
    elif mode == "recover":
        recovered = await recover_workflows("persistence-recovery-worker", apply=True)
        assert state["workflow_id"] in recovered
        write_json(directory / "recovered.json", list(recovered))
    elif mode == "change-descriptor":
        await change_descriptor(state)
    elif mode == "preview":
        await inspect_contract(directory, state, committed=False)
    elif mode in {"confirm-crash", "confirm-replay"}:
        await confirm(directory, state, crash=mode == "confirm-crash")
    elif mode == "finish":
        await finish_cleanup(directory, state)
    else:
        raise ValueError(mode)


if __name__ == "__main__":

    async def run():
        try:
            await main(sys.argv[1], Path(sys.argv[2]))
        finally:
            await engine.dispose()

    asyncio.run(run())
