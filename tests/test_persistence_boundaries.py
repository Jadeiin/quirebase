"""Application guarantees owned by Quirebase, across supported databases."""

from __future__ import annotations

import json
from uuid import uuid4

import pymupdf
import pytest
from advanced_alchemy.types import FileObject
from sqlalchemy import func, select, update
from workspace_helpers import provision_initial_workspace

from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
)
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.library import (
    Contributor,
    ExternalIdentifier,
    ItemMetadata,
    copy_item_to_workspace,
    revise_item_metadata,
    stage_pdf_import_batch,
)
from quirebase.library.imports import extract_pdf_import_doi
from quirebase.models import (
    Attachment,
    AuditEvent,
    Author,
    FileRevision,
    ImportBatch,
    Item,
    ItemAuthor,
    ItemIdentifier,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.search import search_index

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def provision_actor(db, username):
    actor = User(username=username, password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    return actor, workspace.id


@pytest.mark.parametrize("rejection", ["foreign_identity", "viewer", "stale_version"])
async def test_metadata_rejection_preserves_roots_links_search_and_durable_side_effects(
    persistence_sessions, fake_durable_operations, rejection
):
    async with persistence_sessions() as db:
        actor, own_workspace_id = await provision_actor(db, "mutation-actor")
        other, foreign_workspace_id = await provision_actor(db, "mutation-other")
        db.add(
            WorkspaceMember(
                workspace_id=foreign_workspace_id,
                user_id=actor.id,
                role=WorkspaceRole.viewer if rejection == "viewer" else WorkspaceRole.editor,
                invited_by=other.id,
            )
        )
        own = Item(workspace_id=own_workspace_id, created_by=actor.id, title="Protected local")
        foreign = Item(
            workspace_id=foreign_workspace_id, created_by=other.id, title="Protected foreign"
        )
        author = Author(last_name="Protected", first_name="Contributor")
        db.add_all([own, foreign, author])
        await db.flush()
        for item in (own, foreign):
            db.add(ItemAuthor(item_id=item.id, author_id=author.id, position=1, role="author"))
            db.add(ItemIdentifier(item_id=item.id, provider="pmid", value="protected-id"))
            await search_index(db).index_item(db, item.id)
        await db.commit()
        own_id, foreign_id, author_id = own.id, foreign.id, author.id
        enqueues_before = list(fake_durable_operations.enqueues)

        target_workspace_id, target_id, expected_version, error = (
            own_workspace_id,
            foreign_id,
            1,
            ResourceUnavailable,
        )
        if rejection == "viewer":
            target_workspace_id, error = foreign_workspace_id, PermissionDenied
        elif rejection == "stale_version":
            target_id, expected_version, error = own_id, 0, VersionConflict
        with pytest.raises(error):
            await revise_item_metadata(
                db,
                actor,
                target_workspace_id,
                target_id,
                expected_version,
                ItemMetadata(
                    title="Mutation candidate",
                    authors=(Contributor("Replacement", "Contributor"),),
                    identifiers=(ExternalIdentifier("pmid", "replacement-id"),),
                ),
            )
        assert not db.in_transaction()
        assert fake_durable_operations.enqueues == enqueues_before

        async with persistence_sessions() as observer:
            for item_id, title in ((own_id, "Protected local"), (foreign_id, "Protected foreign")):
                persisted = await observer.get(Item, item_id)
                assert (persisted.title, persisted.version) == (title, 1)
                contributor = await observer.scalar(
                    select(ItemAuthor).where(ItemAuthor.item_id == item_id)
                )
                assert (contributor.author_id, contributor.position, contributor.role) == (
                    author_id,
                    1,
                    "author",
                )
                identifier = await observer.scalar(
                    select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)
                )
                assert (identifier.provider, identifier.value) == ("pmid", "protected-id")
            assert await observer.scalar(select(func.count()).select_from(Author)) == 1
            assert (
                await observer.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(AuditEvent.action == "item.update")
                )
                == 0
            )
            assert await search_index(observer).search(observer, "mutation candidate") == []
            assert set(await search_index(observer).search(observer, "protected")) == {
                own_id,
                foreign_id,
            }


@pytest.mark.parametrize("descriptor_kind", ["file", "thumbnail", "attachment"])
async def test_copy_rejects_metadata_only_descriptor_changes_and_cleans_copied_objects(
    persistence_sessions, fake_durable_operations, monkeypatch, descriptor_kind
):
    async with persistence_sessions() as db:
        actor, source_workspace_id = await provision_actor(db, "copy-actor")
        other, target_workspace_id = await provision_actor(db, "copy-other")
        db.add(
            WorkspaceMember(
                workspace_id=target_workspace_id,
                user_id=actor.id,
                role=WorkspaceRole.editor,
                invited_by=other.id,
            )
        )
        source = Item(workspace_id=source_workspace_id, created_by=actor.id, title="Copy source")
        db.add(source)
        await db.flush()
        store = get_object_store()
        stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"%PDF-source", max_bytes=100)
        revision = FileRevision(
            workspace_id=source_workspace_id,
            item_id=source.id,
            created_by=actor.id,
            processing_state="ready",
            file=FileObject(
                backend="documents",
                filename=stored.key,
                size=stored.size,
                metadata={"original_name": "source.pdf"},
            ),
        )
        db.add(revision)
        changed_root, changed_model, changed_column = revision, FileRevision, FileRevision.file
        changed_file = revision.file
        if descriptor_kind == "thumbnail":
            image = await store.put_object(uuid4(), ObjectSuffix.PNG, b"thumbnail", max_bytes=100)
            revision.thumbnail = FileObject(
                backend="documents", filename=image.key, size=image.size, metadata={"page": 1}
            )
            changed_column, changed_file = FileRevision.thumbnail, revision.thumbnail
        elif descriptor_kind == "attachment":
            extra = await store.put_object(
                uuid4(), ObjectSuffix.BINARY, b"attachment", max_bytes=100
            )
            attachment = Attachment(
                workspace_id=source_workspace_id,
                item_id=source.id,
                created_by=actor.id,
                file=FileObject(
                    backend="documents",
                    filename=extra.key,
                    size=extra.size,
                    metadata={"kind": "data"},
                ),
            )
            db.add(attachment)
            changed_root, changed_model, changed_column = attachment, Attachment, Attachment.file
            changed_file = attachment.file
        await db.commit()
        source_id, changed_id, changed_path = source.id, changed_root.id, changed_file.path
        changed_descriptor = FileObject(
            **(changed_file.to_dict() | {"metadata": {"generation": "changed"}})
        )
        copied_paths: list[str] = []
        enqueues_before = list(fake_durable_operations.enqueues)

        class ChangingStore:
            async def get(self, key):
                assert not db.in_transaction()
                if key == changed_path:
                    async with persistence_sessions() as concurrent:
                        await concurrent.execute(
                            update(changed_model)
                            .where(changed_model.id == changed_id)
                            .values({changed_column: changed_descriptor})
                        )
                        await concurrent.commit()
                return await store.get(key)

            async def put_object(self, *args, **kwargs):
                copied = await store.put_object(*args, **kwargs)
                copied_paths.append(copied.key)
                return copied

        monkeypatch.setattr("quirebase.documents.copying.get_object_store", ChangingStore)
        with pytest.raises(ValidationFailure, match="source Item changed"):
            await copy_item_to_workspace(
                db, actor, source_workspace_id, target_workspace_id, source_id
            )
        assert copied_paths and all([not await store.exists(path) for path in copied_paths])
        assert await store.exists(changed_path)
        assert fake_durable_operations.enqueues == enqueues_before
        async with persistence_sessions() as observer:
            assert (
                await observer.scalar(
                    select(func.count())
                    .select_from(Item)
                    .where(Item.workspace_id == target_workspace_id)
                )
                == 0
            )
            assert (
                await observer.scalar(
                    select(func.count())
                    .select_from(AuditEvent)
                    .where(
                        AuditEvent.action.in_([
                            "workspace.item.copy.export",
                            "workspace.item.copy.import",
                        ])
                    )
                )
                == 0
            )
            assert await search_index(observer).search(observer, "copy source") == []
            current = await observer.get(changed_model, changed_id)
            persisted_file = getattr(current, changed_column.key)
            assert persisted_file.path == changed_path
            assert persisted_file.metadata == {"generation": "changed"}


async def test_pdf_durable_inputs_remain_replayable_after_live_descriptor_metadata_changes(
    persistence_sessions, fake_durable_operations, tmp_path
):
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "https://doi.org/10.1000/snapshot")
        contents = document.tobytes()
    async with persistence_sessions() as db:
        actor, workspace_id = await provision_actor(db, "snapshot-actor")
        await db.commit()
        batch, _, _ = await stage_pdf_import_batch(
            db, actor, workspace_id, [(contents, "uploaded.pdf")], max_bytes=100_000
        )
        message = next(
            entry
            for entry in fake_durable_operations.enqueues
            if entry["workflow_name"] == "library.prepare_pdf_import"
        )
        pending = message["args"][-1]
        checkpoint = tmp_path / "durable-inputs.json"
        checkpoint.write_text(json.dumps(pending), encoding="utf-8")
        file = batch.staged_files[0]
        source_id, path, size = file.metadata["source_id"], file.path, file.size
        await db.execute(
            update(ImportBatch)
            .where(ImportBatch.id == batch.id)
            .values(
                staged_files=[
                    FileObject(
                        **(
                            file.to_dict()
                            | {"metadata": file.metadata | {"original_name": "renamed.pdf"}}
                        )
                    )
                ]
            )
        )
        await db.commit()
        await db.refresh(batch)
        assert batch.staged_files[0].metadata["original_name"] == "renamed.pdf"
        replayed = json.loads(checkpoint.read_text(encoding="utf-8"))
        assert replayed == [
            {
                "_row": 1,
                "_source_id": source_id,
                "_pdf": {"object_key": path, "size": size, "original_name": "uploaded.pdf"},
            }
        ]
        assert pending == replayed
        extracted = await extract_pdf_import_doi(replayed[0])
        assert extracted["detected_doi"] == "10.1000/snapshot"
        assert extracted["object_key"] == path
