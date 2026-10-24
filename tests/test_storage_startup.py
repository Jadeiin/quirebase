from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx2
import pytest
from advanced_alchemy.types import FileObject, storages
from app_helpers import create_web_test_app
from import_helpers import pdf_import_batch_data
from workspace_helpers import provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.database import get_db
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.models import (
    Attachment,
    FileRevision,
    ImportBatch,
    Item,
    LoginSession,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)


async def _owner(db):
    actor = User(username="storage-owner", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    db.add(
        LoginSession(
            token_hash=token_hash("storage-test-session"),
            user_id=actor.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    return actor, workspace


@asynccontextmanager
async def _cold_web_client(db, session_factory):
    previous_backend = storages.get_backend("documents")
    storages.unregister_backend("documents")
    get_object_store.cache_clear()
    # Reload descriptors instead of retaining FileObject's resolved backend cache.
    db.expunge_all()
    try:
        app = create_web_test_app(mcp_session_factory=session_factory)

        async def database():
            await asyncio.sleep(0)
            yield db

        app.dependency_overrides[get_db] = database
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Origin": "http://testserver"},
            ) as client,
        ):
            client.cookies.set(get_settings().session_cookie, "storage-test-session")
            yield client
    finally:
        get_object_store.cache_clear()
        storages.register_backend(previous_backend)


@pytest.mark.anyio
async def test_web_cold_start_can_copy_item_documents(async_db, async_session_factory):
    db = async_db
    actor, workspace = await _owner(db)
    target = Workspace(name="Copy target", created_by=actor.id)
    item = Item(
        workspace_id=workspace.id,
        created_by=actor.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Copy source"},
    )
    db.add_all([target, item])
    await db.flush()
    db.add(WorkspaceMember(workspace_id=target.id, user_id=actor.id, role=WorkspaceRole.owner))
    store = get_object_store()
    pdf = await store.put_object(uuid4(), ObjectSuffix.PDF, b"%PDF-source", max_bytes=100)
    supplement = await store.put_object(uuid4(), ObjectSuffix.BINARY, b"supplement", max_bytes=100)
    db.add_all([
        FileRevision(
            workspace_id=workspace.id,
            item_id=item.id,
            created_by=actor.id,
            processing_state="ready",
            file=FileObject(
                backend="documents",
                filename=pdf.key,
                size=pdf.size,
                content_type="application/pdf",
                metadata={"original_name": "source.pdf"},
            ),
        ),
        Attachment(
            workspace_id=workspace.id,
            item_id=item.id,
            created_by=actor.id,
            file=FileObject(
                backend="documents",
                filename=supplement.key,
                size=supplement.size,
                metadata={"original_name": "supplement.bin"},
            ),
        ),
    ])
    await db.commit()
    workspace_id, item_id, target_id = workspace.id, item.id, target.id

    async with _cold_web_client(db, async_session_factory) as client:
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/items/{item_id}/copy",
            json={"target_workspace_id": str(target_id)},
        )
        assert response.status_code == 201, response.text
        copied_id = response.json()["target_item_id"]
        base = f"/api/v1/workspaces/{target_id}/items/{copied_id}"
        documents = await client.get(f"{base}/documents")
        assert documents.status_code == 200, documents.text
        files = {file["kind"]: file for file in documents.json()["files"]}
        assert files["revision"]["original_name"] == "source.pdf"
        assert files["attachment"]["original_name"] == "supplement.bin"
        pdf_response = await client.get(f"{base}/revisions/{files['revision']['id']}/content")
        assert pdf_response.status_code == 200
        assert pdf_response.content == b"%PDF-source"
        supplement_response = await client.get(
            f"{base}/attachments/{files['attachment']['id']}/content"
        )
        assert supplement_response.status_code == 200
        assert supplement_response.content == b"supplement"


@pytest.mark.anyio
async def test_web_cold_start_can_confirm_pdf_import(async_db, async_session_factory):
    db = async_db
    actor, workspace = await _owner(db)
    pdf = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-import", max_bytes=100
    )
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=actor.id,
        file_format="pdf",
        status="ready",
        errors=[],
        **pdf_import_batch_data([
            {
                "work": {
                    "id": f"urn:uuid:{uuid4()}",
                    "type": "Document",
                    "title": "Imported PDF",
                },
                "_pdf": {
                    "object_key": pdf.key,
                    "size": pdf.size,
                    "original_name": "import.pdf",
                },
            }
        ]),
    )
    db.add(batch)
    await db.commit()
    workspace_id, batch_id = workspace.id, batch.id

    async with _cold_web_client(db, async_session_factory) as client:
        preview = (await client.get(f"/api/v1/workspaces/{workspace_id}/imports/{batch_id}")).json()
        response = await client.post(
            f"/api/v1/workspaces/{workspace_id}/imports/{batch_id}/commit",
            json={"expected_preview_version": preview["preview_version"]},
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["status"] == "committed"
        assert len(receipt["committed_item_ids"]) == 1
        item_id = receipt["committed_item_ids"][0]
        base = f"/api/v1/workspaces/{workspace_id}/items/{item_id}"
        documents = await client.get(f"{base}/documents")
        assert documents.status_code == 200, documents.text
        files = documents.json()["files"]
        assert len(files) == 1
        assert files[0]["original_name"] == "import.pdf"
        pdf_response = await client.get(f"{base}/revisions/{files[0]['id']}/content")
        assert pdf_response.status_code == 200
        assert pdf_response.content == b"%PDF-import"
