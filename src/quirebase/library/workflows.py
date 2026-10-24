from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from dbos import DBOS
from sqlalchemy import select, update

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.core.database import AsyncSessionLocal
from quirebase.core.workflows import (
    DOCUMENT_CLEANUP_QUEUE,
    RECOMMENDATION_QUEUE,
    ads,
    durable_operations,
    enqueue_child_workflow,
    object_reservation_attributes,
)
from quirebase.documents.events import FILE_REVISION_CHANGED_WORKFLOW, OBJECT_CLEANUP_WORKFLOW
from quirebase.models import ImportBatch, ImportBatchStatus, Item, ItemTagRecommendation, User

from .tag_recommendations import (
    RecommendationCandidates,
    recommend_item_tags,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

RECOMMEND_TAGS_WORKFLOW = "library.recommend_tags"
PREPARE_PDF_IMPORT_WORKFLOW = "library.prepare_pdf_import"
_PDF_LOOKUP_ATTEMPTS = 3
_PDF_LOOKUP_WAIT_BUDGET_SECONDS = 60.0


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
    item_id: UUID,
    *,
    workspace_id: UUID,
    actor_id: UUID,
    force: bool = False,
) -> ItemTagRecommendation:
    """Create an idempotent generation request without committing its caller's transaction."""
    actor = await db.get(User, actor_id)
    if actor is None:
        raise ValueError("recommendation actor is unavailable")
    await require_workspace_action(db, actor, workspace_id, ResourceAction.item_update)
    if (
        await db.scalar(
            select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        )
        is None
    ):
        raise ValueError("Item does not belong to the requested Workspace")
    # Inspect the durable workflow before taking the recommendation row lock.  A slow DBOS
    # lookup must not block other recommendation requests or Item mutations.
    observed_record = await db.scalar(
        select(ItemTagRecommendation).where(
            ItemTagRecommendation.item_id == item_id,
            ItemTagRecommendation.workspace_id == workspace_id,
        )
    )
    observed_workflow_id = observed_record.workflow_id if observed_record else None
    workflow = await _linked_workflow(observed_record) if observed_record and not force else None
    if db.get_bind().dialect.name == "postgresql":
        item_lock = select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        # An absent recommendation row cannot be locked. Serialize its creation
        # on the Item root; existing generations serialize on their own row.
        item_lock = (
            item_lock.with_for_update(key_share=True)
            if observed_record is None
            else item_lock.with_for_update(read=True, key_share=True)
        )
        locked_item_id = await db.scalar(item_lock)
    else:
        locked_item_id = await db.scalar(
            select(Item.id).where(Item.id == item_id, Item.workspace_id == workspace_id)
        )
    if locked_item_id is None:
        raise ValueError("Item no longer exists")
    record = await db.scalar(
        select(ItemTagRecommendation)
        .where(
            ItemTagRecommendation.item_id == item_id,
            ItemTagRecommendation.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update(key_share=True)
    )
    if (
        record is not None
        and not force
        and (
            observed_record is None
            or record.generated_at is not None
            or (
                record.workflow_id == observed_workflow_id
                and workflow is not None
                and workflow.state in {"pending", "running", "succeeded"}
            )
        )
    ):
        return record

    token = (record.generation_token + 1) if record else 1
    if record is None:
        record = ItemTagRecommendation(
            workspace_id=workspace_id,
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
        actor_id,
        workspace_id,
        item_id,
        token,
        workflow_id,
        queue_name=RECOMMENDATION_QUEUE,
        workflow_id=workflow_id,
        attributes={
            "capability": "library",
            "actor_id": actor_id,
            "workspace_id": workspace_id,
            "item_id": item_id,
        },
    )
    record.workflow_id = workflow_id
    await db.flush()
    return record


async def _store_item_tag_recommendation(
    db: AsyncSession,
    actor_id: UUID,
    workspace_id: UUID,
    item_id: UUID,
    generation_token: int,
    workflow_id: str,
    candidates: RecommendationCandidates,
) -> dict[str, Any]:
    actor = await db.get(User, actor_id)
    if actor is None:
        return {"unauthorized": True}
    await require_workspace_action(db, actor, workspace_id, ResourceAction.item_update)
    item = await db.scalar(
        select(Item).where(Item.id == item_id, Item.workspace_id == workspace_id).with_for_update()
    )
    if item is None:
        return {"deleted": True}
    record = await db.scalar(
        select(ItemTagRecommendation)
        .where(
            ItemTagRecommendation.item_id == item_id,
            ItemTagRecommendation.workspace_id == workspace_id,
        )
        .with_for_update(key_share=True)
    )
    if (
        record is None
        or record.generation_token != generation_token
        or record.workflow_id != workflow_id
    ):
        return {"stale": True}
    record.single_words = candidates["single_words"]
    record.phrases = candidates["phrases"]
    record.generated_at = datetime.now(UTC)
    return {
        "single_words": len(candidates["single_words"]),
        "phrases": len(candidates["phrases"]),
    }


async def item_ids_for_tag_recommendation(
    db: AsyncSession, workspace_id: UUID, after_id: UUID | None, limit: int
) -> tuple[UUID, ...]:
    query = select(Item.id).where(Item.workspace_id == workspace_id).order_by(Item.id).limit(limit)
    if after_id is not None:
        query = query.where(Item.id > after_id)
    return tuple((await db.scalars(query)).all())


@DBOS.step(retries_allowed=True, max_attempts=3)
async def extract_pdf_import_identifier_step(pending: dict[str, Any]) -> dict[str, Any]:
    from .imports import extract_pdf_import_identifier

    return await extract_pdf_import_identifier(pending)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def lookup_pdf_import_candidates_step(
    batch_id: UUID,
    pending_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from .imports import lookup_pdf_import_candidates

    async with AsyncSessionLocal() as db:
        return await lookup_pdf_import_candidates(db, batch_id, pending_records)


async def _lookup_pdf_import_with_backoff(
    batch_id: UUID,
    pending_records: list[dict[str, Any]],
    wait_budget: float,
) -> tuple[list[dict[str, Any]], float]:
    """Checkpoint each Provider group's outcomes and retry only unavailable sources."""
    remaining = pending_records
    results: dict[str, dict[str, Any]] = {}
    for attempt in range(_PDF_LOOKUP_ATTEMPTS):
        outcomes = await lookup_pdf_import_candidates_step(batch_id, remaining)
        failed = []
        delays = []
        for pending, result in zip(remaining, outcomes, strict=True):
            results[pending["_source_id"]] = result
            if isinstance(failure := result.get("retry"), dict):
                failed.append(pending)
                delay = failure["retry_after_seconds"]
                delays.append(delay if delay is not None else 5.0 * (2**attempt))
        if not failed:
            break
        delay = max(delays)
        if attempt == _PDF_LOOKUP_ATTEMPTS - 1 or delay > wait_budget:
            break
        await DBOS.sleep_async(delay)
        wait_budget -= delay
        remaining = failed
    return [results[pending["_source_id"]] for pending in pending_records], wait_budget


@ads.transaction()
async def finalize_pdf_import_batch_step(
    actor_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
    workflow_id: str,
    records: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> bool:
    from .imports import finalize_pdf_import_batch

    return await finalize_pdf_import_batch(
        ads.sql_session(), actor_id, workspace_id, batch_id, workflow_id, records, errors
    )


@ads.transaction()
async def fail_pdf_import_batch_step(batch_id: UUID, workflow_id: str) -> bool:
    """Publish terminal failure only for the workflow generation that still owns the batch."""
    result = await ads.sql_session().execute(
        update(ImportBatch)
        .where(
            ImportBatch.id == batch_id,
            ImportBatch.status == "pending",
            ImportBatch.workflow_id == workflow_id,
        )
        .values(status=ImportBatchStatus.failed)
    )
    return getattr(result, "rowcount", 0) == 1


@DBOS.workflow(name=PREPARE_PDF_IMPORT_WORKFLOW)
async def prepare_pdf_import_workflow(
    actor_id: UUID,
    workspace_id: UUID,
    batch_id: UUID,
    workflow_id: str,
    pending_records: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        records: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        rejected_keys: list[str] = []
        wait_budget = _PDF_LOOKUP_WAIT_BUDGET_SECONDS
        all_keys = [pending["_pdf"]["object_key"] for pending in pending_records]
        results: dict[str, dict[str, Any]] = {}
        groups: dict[str, list[dict[str, Any]]] = {}
        for pending in pending_records:
            if "_lookup" not in pending:
                result = await extract_pdf_import_identifier_step(pending)
                if "detected_identifier" not in result:
                    results[pending["_source_id"]] = result
                    continue
                pending = {**pending, "_lookup": result["detected_identifier"]}
            groups.setdefault(pending["_lookup"]["provider"], []).append(pending)
        for group in groups.values():
            outcomes, wait_budget = await _lookup_pdf_import_with_backoff(
                batch_id, group, wait_budget
            )
            results.update(
                (pending["_source_id"], result)
                for pending, result in zip(group, outcomes, strict=True)
            )
        for pending in pending_records:
            result = results[pending["_source_id"]]
            if isinstance(result.get("error"), dict):
                errors.append(result["error"])
            if isinstance(result.get("record"), dict):
                records.append(result["record"])
            else:
                rejected_keys.append(result["object_key"])
        finalized = await finalize_pdf_import_batch_step(
            actor_id, workspace_id, batch_id, workflow_id, records, errors
        )
        cleanup_keys = rejected_keys if finalized else all_keys
        if cleanup_keys:
            await enqueue_child_workflow(
                OBJECT_CLEANUP_WORKFLOW,
                actor_id,
                workspace_id,
                cleanup_keys,
                workflow_id,
                queue_name=DOCUMENT_CLEANUP_QUEUE,
                workflow_id=f"prepare-pdf-import-cleanup:{workflow_id}",
                attributes={
                    "capability": "documents",
                    "operation": "pdf_import_cleanup",
                    "actor_id": actor_id,
                    "workspace_id": workspace_id,
                    "batch_id": batch_id,
                    **object_reservation_attributes(cleanup_keys, intent="cleanup"),
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


@DBOS.step(retries_allowed=True, max_attempts=3)
async def request_item_tag_recommendation_step(
    actor_id: UUID, workspace_id: UUID, item_id: UUID
) -> None:
    """Retry the idempotent request boundary, including its separate DBOS Client lookup."""
    async with AsyncSessionLocal() as db:
        try:
            actor = await db.get(User, actor_id)
            if actor is None:
                return
            await require_workspace_action(db, actor, workspace_id, ResourceAction.item_update)
            await request_item_tag_recommendation(
                db,
                item_id,
                workspace_id=workspace_id,
                actor_id=actor_id,
                force=True,
            )
        except ValueError:
            # File Revision events may outlive their deleted Item.
            return
        await db.commit()


@DBOS.workflow(name=FILE_REVISION_CHANGED_WORKFLOW)
async def file_revision_changed_workflow(
    actor_id: UUID, workspace_id: UUID, revision_id: UUID, item_id: UUID
) -> None:
    await request_item_tag_recommendation_step(actor_id, workspace_id, item_id)


@DBOS.step(retries_allowed=True, max_attempts=3)
async def generate_item_tag_recommendation_step(
    item_id: UUID,
) -> RecommendationCandidates | None:
    """Retry a read-only generation; its checkpoint contains no Item full text."""
    async with AsyncSessionLocal() as db:
        try:
            return await recommend_item_tags(db, item_id)
        except ValueError:
            # Deletion between the validity check and inference is a normal race.
            return None


@ads.transaction(isolation_level="READ COMMITTED")
async def item_tag_recommendation_is_current_step(
    item_id: UUID,
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
    actor_id: UUID,
    workspace_id: UUID,
    item_id: UUID,
    generation_token: int,
    workflow_id: str,
    candidates: RecommendationCandidates,
) -> dict[str, Any]:
    db = ads.sql_session()
    return await _store_item_tag_recommendation(
        db, actor_id, workspace_id, item_id, generation_token, workflow_id, candidates
    )


@DBOS.workflow(name=RECOMMEND_TAGS_WORKFLOW)
async def recommend_tags_workflow(
    actor_id: UUID,
    workspace_id: UUID,
    item_id: UUID,
    generation_token: int,
    workflow_id: str,
) -> dict[str, Any]:
    if not await item_tag_recommendation_is_current_step(item_id, generation_token, workflow_id):
        return {"stale": True}
    candidates = await generate_item_tag_recommendation_step(item_id)
    if candidates is None:
        return {"deleted": True}
    return await commit_item_tag_recommendation_step(
        actor_id, workspace_id, item_id, generation_token, workflow_id, candidates
    )
