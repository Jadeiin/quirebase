from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dbos import DBOS
from sqlalchemy import select, update

from quirebase.core.database import AsyncSessionLocal
from quirebase.core.workflows import (
    DOCUMENT_CLEANUP_QUEUE,
    RECOMMENDATION_QUEUE,
    ads,
    durable_operations,
    enqueue_child_workflow,
)
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW, OBJECT_CLEANUP_WORKFLOW
from quirebase.models import ImportBatch, Item, ItemTagRecommendation
from quirebase.search import search_index

from .tag_recommendations import (
    RecommendationCandidates,
    recommend_item_tags,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

RECOMMEND_TAGS_WORKFLOW = "library.recommend_tags"
PREPARE_PDF_IMPORT_WORKFLOW = "library.prepare_pdf_import"


async def _linked_workflow(record: ItemTagRecommendation):
    return await durable_operations().get(record.workflow_id) if record.workflow_id else None


async def item_tag_recommendation_status(
    record: ItemTagRecommendation | None,
) -> tuple[str, str | None]:
    if record is None:
        return "empty", None
    if record.generated_at is not None:
        return "ready", None
    workflow = await _linked_workflow(record)
    if workflow is None or workflow.state in {"failed", "cancelled"}:
        return "failed", workflow.error if workflow else None
    return "pending", None


async def request_item_tag_recommendation(
    db: AsyncSession,
    item_id: str,
    *,
    owner_id: str | None = None,
    force: bool = False,
) -> ItemTagRecommendation:
    """Create an idempotent generation request without committing its caller's transaction."""
    if force:
        if db.get_bind().dialect.name == "sqlite":
            locked_item_id = await db.scalar(
                update(Item)
                .where(Item.id == item_id)
                .values(updated_at=Item.updated_at)
                .returning(Item.id)
            )
        else:
            locked_item_id = await db.scalar(
                select(Item.id).where(Item.id == item_id).with_for_update()
            )
        if locked_item_id is None:
            raise ValueError("Item no longer exists")
    elif await db.get(Item, item_id) is None:
        raise ValueError("Item no longer exists")
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if record is not None and not force:
        workflow = await _linked_workflow(record)
        if record.generated_at is not None or (
            workflow is not None and workflow.state in {"pending", "running", "succeeded"}
        ):
            return record

    token = (record.generation_token + 1) if record else 1
    if record is None:
        record = ItemTagRecommendation(
            item_id=item_id,
            generation_token=token,
        )
        db.add(record)
    else:
        record.generation_token = token
        record.single_words = None
        record.phrases = None
        record.generated_at = None
    workflow_id = f"item-recommend-tags:{item_id}:{token}"
    await db.flush()
    await durable_operations().enqueue_in_transaction(
        db,
        RECOMMEND_TAGS_WORKFLOW,
        item_id,
        token,
        workflow_id,
        queue_name=RECOMMENDATION_QUEUE,
        workflow_id=workflow_id,
        attributes={"capability": "library", "owner_id": owner_id, "item_id": item_id},
    )
    record.workflow_id = workflow_id
    await db.flush()
    return record


async def _store_item_tag_recommendation(
    db: AsyncSession,
    item_id: str,
    generation_token: int,
    workflow_id: str,
    candidates: RecommendationCandidates,
) -> dict[str, Any]:
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    if (
        record is None
        or record.generation_token != generation_token
        or record.workflow_id != workflow_id
    ):
        return {"stale": True}
    record.single_words = json.dumps(candidates["single_words"], ensure_ascii=False)
    record.phrases = json.dumps(candidates["phrases"], ensure_ascii=False)
    record.generated_at = datetime.now(UTC)
    return {
        "single_words": len(candidates["single_words"]),
        "phrases": len(candidates["phrases"]),
    }


async def item_ids_for_tag_recommendation(db: AsyncSession) -> tuple[str, ...]:
    return tuple((await db.scalars(select(Item.id).order_by(Item.id))).all())


@DBOS.step(retries_allowed=True, max_attempts=3)
async def prepare_pdf_import_candidate_step(
    batch_id: str, pending: dict[str, Any]
) -> dict[str, Any]:
    from .imports import prepare_pdf_import_candidate

    async with AsyncSessionLocal() as db:
        return await prepare_pdf_import_candidate(db, batch_id, pending)


@ads.transaction()
async def finalize_pdf_import_batch_step(
    batch_id: str,
    workflow_id: str,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> bool:
    from .imports import finalize_pdf_import_batch

    return await finalize_pdf_import_batch(
        ads.sql_session(), batch_id, workflow_id, records, errors
    )


@ads.transaction()
async def fail_pdf_import_batch_step(batch_id: str, workflow_id: str) -> bool:
    """Publish terminal failure only for the workflow generation that still owns the batch."""
    batch = await ads.sql_session().get(ImportBatch, batch_id)
    if batch is None or batch.status != "pending" or batch.workflow_id != workflow_id:
        return False
    batch.status = "failed"
    return True


@DBOS.workflow(name=PREPARE_PDF_IMPORT_WORKFLOW)
async def prepare_pdf_import_workflow(
    batch_id: str,
    workflow_id: str,
    pending_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        records: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        rejected_keys: list[str] = []
        seen_dois: set[str] = set()
        all_keys = [pending["_pdf"]["object_key"] for pending in pending_records]
        for pending in pending_records:
            result = await prepare_pdf_import_candidate_step(batch_id, pending)
            normalized_doi = result.get("normalized_doi")
            if isinstance(normalized_doi, str) and normalized_doi in seen_dois:
                pdf = pending["_pdf"]
                errors.append({
                    "row": pending["_row"],
                    "filename": pdf["original_name"],
                    "code": "duplicate_batch_doi",
                    "message": "another PDF in this batch has the same DOI",
                })
                rejected_keys.append(pdf["object_key"])
            elif isinstance(result.get("record"), dict):
                records.append(result["record"])
                if isinstance(normalized_doi, str):
                    seen_dois.add(normalized_doi)
            else:
                if isinstance(result.get("error"), dict):
                    errors.append(result["error"])
                rejected_keys.append(result["object_key"])
        finalized = await finalize_pdf_import_batch_step(batch_id, workflow_id, records, errors)
        cleanup_keys = rejected_keys if finalized else all_keys
        if cleanup_keys:
            await enqueue_child_workflow(
                OBJECT_CLEANUP_WORKFLOW,
                cleanup_keys,
                workflow_id,
                queue_name=DOCUMENT_CLEANUP_QUEUE,
                workflow_id=f"prepare-pdf-import-cleanup:{workflow_id}",
                attributes={
                    "capability": "documents",
                    "operation": "pdf_import_cleanup",
                    "batch_id": batch_id,
                    "object_keys": cleanup_keys,
                },
            )
        return {
            "candidates": len(records),
            "diagnostics": len(errors),
            "discarded": not finalized,
        }
    except Exception:
        await fail_pdf_import_batch_step(batch_id, workflow_id)
        raise


@ads.transaction()
async def apply_file_revision_changed(item_id: str) -> None:
    db = ads.sql_session()
    await search_index(db).index_item(db, item_id)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def request_item_tag_recommendation_step(item_id: str, owner_id: str | None) -> None:
    """Retry the idempotent request boundary, including its separate DBOS Client lookup."""
    async with AsyncSessionLocal() as db:
        try:
            await request_item_tag_recommendation(db, item_id, owner_id=owner_id, force=True)
        except ValueError:
            # File Revision events may outlive their deleted Item.
            return
        await db.commit()


@DBOS.workflow(name=FILE_REVISION_CHANGED_WORKFLOW)
async def file_revision_changed_workflow(item_id: str, owner_id: str | None) -> None:
    await apply_file_revision_changed(item_id)
    await request_item_tag_recommendation_step(item_id, owner_id)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def generate_item_tag_recommendation_step(
    item_id: str,
) -> RecommendationCandidates | None:
    """Retry a read-only generation; its checkpoint contains no Item full text."""
    async with AsyncSessionLocal() as db:
        try:
            return await recommend_item_tags(db, item_id)
        except ValueError:
            # Deletion between the validity check and inference is a normal race.
            return None


@ads.transaction()
async def item_tag_recommendation_is_current_step(
    item_id: str,
    generation_token: int,
    workflow_id: str,
) -> bool:
    db = ads.sql_session()
    record = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item_id)
    )
    return bool(
        record is not None
        and record.generation_token == generation_token
        and record.workflow_id == workflow_id
    )


@ads.transaction()
async def commit_item_tag_recommendation_step(
    item_id: str,
    generation_token: int,
    workflow_id: str,
    candidates: RecommendationCandidates,
) -> dict[str, Any]:
    db = ads.sql_session()
    return await _store_item_tag_recommendation(
        db, item_id, generation_token, workflow_id, candidates
    )


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_workflow(
    item_id: str,
    generation_token: int,
    workflow_id: str,
) -> dict[str, Any]:
    if not await item_tag_recommendation_is_current_step(item_id, generation_token, workflow_id):
        return {"stale": True}
    candidates = await generate_item_tag_recommendation_step(item_id)
    if candidates is None:
        return {"deleted": True}
    return await commit_item_tag_recommendation_step(
        item_id, generation_token, workflow_id, candidates
    )
