"""Isolated-process driver for the real PDF import/recovery contract."""

from __future__ import annotations

import asyncio
import json
import sys
from contextlib import suppress
from pathlib import Path
from uuid import UUID, uuid4

import pymupdf
from advanced_alchemy.types import FileObject
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro.models import CandidateRecord, Identifier, LookupFailure, LookupOutcome
from item_helpers import work_identifier
from sqlalchemy import func, select, update
from workspace_helpers import provision_initial_workspace

from quirebase.cli import _register_workflows
from quirebase.core.database import AsyncSessionLocal, engine
from quirebase.core.storage import get_object_store
from quirebase.core.workflows import durable_operations, launch_worker, recover_workflows
from quirebase.library import (
    commit_import_batch,
    get_import_batch_preview,
    imports,
    stage_pdf_import_batch,
)
from quirebase.models import (
    AuditEvent,
    FileRevision,
    FileRevisionProcessingState,
    ImportBatch,
    Item,
    ItemTagRecommendation,
    User,
)
from quirebase.search import search_index


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def instrument_external_provider(directory, *, pause, rate_limit=False, exhaust=False):
    extract = imports.extract_pdf_import_identifier

    async def observed_extract(pending):
        result = await extract(pending)
        with (directory / "extractions.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(pending["_pdf"]) + "\n")
        return result

    async def lookup(identifier, _identifier_type, _settings):
        if rate_limit:
            with (directory / "provider-calls.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps(identifier) + "\n")
        if identifier.endswith("recovery-rejected"):
            if rate_limit:
                seen = directory / "rate-limit-seen"
                if exhaust or not seen.exists():
                    seen.touch()
                    return LookupFailure(
                        "unavailable", "provider rate limit was reached", True, 0 if exhaust else 5
                    )
            elif pause:
                (directory / "checkpoint-reached").touch()
                await asyncio.Event().wait()
            else:
                return LookupFailure("not_found", "no metadata for this PDF")
        return CandidateRecord(
            provider="crossref",
            lookup_identifier=Identifier("doi", identifier),
            work=compact({
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Recovery retained paper",
                "contributors": (get_one_author({"name": "Recovery, Author"}),),
                "identifiers": [work_identifier("doi", identifier)],
            }),
        )

    imports.extract_pdf_import_identifier = observed_extract

    async def lookup_many(values, provider, settings):
        outcomes = []
        for value in values:
            result = await lookup(value, provider, settings)
            outcomes.append(LookupOutcome(value, result))
        return tuple(outcomes)

    imports.lookup_candidates = lookup_many


async def stage(directory):
    uploads = []
    for suffix in ("kept", "rejected"):
        with pymupdf.open() as document:
            document.new_page().insert_text((72, 72), f"https://doi.org/10.1000/recovery-{suffix}")
            document.set_metadata({"subject": f"doi:10.1000/recovery-{suffix}"})
            uploads.append((document.tobytes(), f"uploaded-{suffix}.pdf"))
    async with AsyncSessionLocal() as db:
        actor = User(username="recovery-owner", password_hash="unused")
        db.add(actor)
        await db.flush()
        workspace = await provision_initial_workspace(db, actor)
        await db.commit()
        preview = await stage_pdf_import_batch(db, actor, workspace.id, uploads)
        batch = await db.get(ImportBatch, preview.id)
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
        preview = await get_import_batch_preview(
            db, actor, UUID(state["workspace_id"]), UUID(state["batch_id"])
        )
        ids = (
            await commit_import_batch(
                db,
                actor,
                UUID(state["workspace_id"]),
                UUID(state["batch_id"]),
                expected_preview_version=preview.preview_version,
            )
        ).committed_item_ids
        if crash:
            (directory / "confirmation-committed").touch()
            await asyncio.Event().wait()
        write_json(directory / "confirmed.json", [str(item_id) for item_id in ids])


async def finish_import(directory, state):
    async with AsyncSessionLocal() as db:
        revision = (await db.scalars(select(FileRevision))).one()
        assert revision.processing_workflow_id is not None
        item_id = revision.item_id
        cleanups = [
            workflow.id
            for workflow in await durable_operations().list(limit=100)
            if workflow.name == "documents.cleanup_objects"
        ]
        assert len(cleanups) == 1
        followups = (
            *cleanups,
            revision.processing_workflow_id,
            f"file-revision-changed:{revision.id}",
        )
    worker = asyncio.create_task(launch_worker())
    try:
        async with asyncio.timeout(30):
            while True:
                statuses = [await durable_operations().get(identity) for identity in followups]
                if all(status is not None and status.state == "succeeded" for status in statuses):
                    async with AsyncSessionLocal() as db:
                        recommendation_id = await db.scalar(
                            select(ItemTagRecommendation.workflow_id).where(
                                ItemTagRecommendation.item_id == item_id
                            )
                        )
                    recommendation = (
                        await durable_operations().get(recommendation_id)
                        if recommendation_id
                        else None
                    )
                    if recommendation is not None and recommendation.state == "succeeded":
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
        preview = await get_import_batch_preview(
            db, actor, UUID(state["workspace_id"]), UUID(state["batch_id"])
        )
        records = preview.records
        diagnostics = preview.errors
        batch = await db.get(ImportBatch, preview.id)
        assert batch.status == ("committed" if committed else "ready")
        assert (
            records == ()
            if committed
            else len(records) == 2
            and records[0].metadata.title == "Recovery retained paper"
            and records[1].is_basic
        )
        if committed:
            assert diagnostics == ()
            assert batch.workflow_id is None
        else:
            assert len(diagnostics) == 1
            assert diagnostics[0].filename == "uploaded-rejected.pdf"
            assert diagnostics[0].code == "metadata_not_found"
        events = list(await db.scalars(select(AuditEvent)))
        assert sum(event.action == "pdf.import.preview.request" for event in events) == 1
        assert sum(event.action == "pdf.import.preview" for event in events) == 1
        if not committed:
            assert len(batch.staged_files) == 2
            assert batch.staged_files[0].path == state["files"][0]["filename"]
            assert await db.scalar(select(func.count()).select_from(Item)) == 0
            return
        expected_ids = json.loads((directory / "confirmed.json").read_text(encoding="utf-8"))
        items = list(await db.scalars(select(Item)))
        revisions = list(await db.scalars(select(FileRevision)))
        assert [str(item.id) for item in items] == expected_ids == batch.committed_item_ids
        assert not batch.staged_files and len(revisions) == 1
        assert revisions[0].item_id == items[0].id
        assert revisions[0].processing_state is FileRevisionProcessingState.ready
        assert revisions[0].file.path == state["files"][0]["filename"]
        assert sum(event.action == "pdf.import" for event in events) == 1
        hits = await search_index(db).search(db, "Recovery")
        assert set(hits) == {items[0].id}
        workflows = await durable_operations().list(limit=100)
        names = [row.name for row in workflows]
        assert names.count("library.prepare_pdf_import") == 1
        assert names.count("documents.cleanup_objects") == 1
        # Metadata import and the ready PDF each request one recommendation generation.
        assert {row.id for row in workflows if row.name == "library.recommend_tags"} == {
            f"item-recommend-tags:{items[0].id}:1",
            f"item-recommend-tags:{items[0].id}:2",
        }
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
    rate_limit = mode in {"worker-rate", "recover-rate", "preview-rate", "run-rate-exhausted"}
    instrument_external_provider(
        directory,
        pause=mode == "worker",
        rate_limit=rate_limit,
        exhaust=mode == "run-rate-exhausted",
    )
    if mode == "worker-rate":
        from dbos import DBOS

        sleep = DBOS.sleep_async

        async def observed_sleep(seconds):
            (directory / "backoff-started").touch()
            await sleep(seconds)

        DBOS.sleep_async = staticmethod(observed_sleep)
        await launch_worker()
    elif mode == "worker":
        await launch_worker()
    elif mode in {"recover", "recover-rate"}:
        recovered = await recover_workflows("persistence-recovery-worker", apply=True)
        assert state["workflow_id"] in recovered
        write_json(directory / "recovered.json", list(recovered))
    elif mode == "run-rate-exhausted":
        worker = asyncio.create_task(launch_worker())
        try:
            async with asyncio.timeout(60):
                while True:
                    if worker.done():
                        worker.result()
                    status = await durable_operations().get(state["workflow_id"])
                    if status.is_terminal:
                        assert status.state == "succeeded", status.error
                        break
                    await asyncio.sleep(0.05)
            await inspect_rate_limit_contract(directory, state, exhausted=True)
        finally:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
    elif mode == "preview-rate":
        await inspect_rate_limit_contract(directory, state, exhausted=False)
    elif mode == "change-descriptor":
        await change_descriptor(state)
    elif mode == "preview":
        await inspect_contract(directory, state, committed=False)
    elif mode in {"confirm-crash", "confirm-replay"}:
        await confirm(directory, state, crash=mode == "confirm-crash")
    elif mode == "finish":
        await finish_import(directory, state)
    else:
        raise ValueError(mode)


async def inspect_rate_limit_contract(directory, state, *, exhausted):
    status = await durable_operations().get(state["workflow_id"])
    assert status.state == "succeeded"
    async with AsyncSessionLocal() as db:
        actor = await db.get(User, UUID(state["actor_id"]))
        preview = await get_import_batch_preview(
            db, actor, UUID(state["workspace_id"]), UUID(state["batch_id"])
        )
        assert preview.status == "ready" and len(preview.records) == 2
        assert not preview.records[0].is_basic
        assert preview.records[1].is_basic is exhausted
        assert [error.code for error in preview.errors] == (
            ["provider_rate_limited"] if exhausted else []
        )
        batch = await db.get(ImportBatch, preview.id)
        assert len(batch.staged_files) == 2
        for file in batch.staged_files:
            assert await get_object_store().exists(file.path)
    extractions = (directory / "extractions.jsonl").read_text().splitlines()
    calls = [
        json.loads(line) for line in (directory / "provider-calls.jsonl").read_text().splitlines()
    ]
    assert len(extractions) == 2
    assert calls.count("10.1000/recovery-kept") == 1
    assert calls.count("10.1000/recovery-rejected") == (3 if exhausted else 2)


if __name__ == "__main__":

    async def run():
        try:
            await main(sys.argv[1], Path(sys.argv[2]))
        finally:
            await engine.dispose()

    asyncio.run(run())
