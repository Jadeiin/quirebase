from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject, storages
from advanced_alchemy.types.file_object.backends.obstore import ObstoreBackend
from obstore.store import S3Store
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.accounts import create_api_token
from quirebase.core.config import get_settings
from quirebase.core.storage import ObjectStore, ObjectSuffix, SignedDownload, get_object_store
from quirebase.documents.exports import get_export_file
from quirebase.documents.workflows import ANNOTATION_EXPORT_WORKFLOW
from quirebase.models import (
    ExportArtifact,
    User,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)


@pytest.fixture(autouse=True)
def reload_download_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.anyio
async def test_native_s3_signing_limits_artifact_lifetime_without_network(monkeypatch):
    monkeypatch.setenv("QUIREBASE_SIGNED_DOWNLOADS", "true")
    get_settings.cache_clear()
    original = get_object_store()
    try:
        store = ObjectStore(
            S3Store(
                "quirebase-test",
                region="us-east-1",
                access_key_id="test-key",
                secret_access_key="test-secret",
            )
        )
        file = FileObject(backend="documents", filename="aa/bb/example.pdf", size=10)
        expiry = datetime.now(UTC) + timedelta(seconds=31)
        signed = await store.sign_download(file, expires_at=expiry)
        assert isinstance(signed, SignedDownload)
        assert signed.expires_at <= expiry
        parsed = urlsplit(signed.url)
        assert parsed.scheme == "https" and parsed.path.endswith("/aa/bb/example.pdf")
        assert 1 <= int(parse_qs(parsed.query)["X-Amz-Expires"][0]) <= 30
        with pytest.raises(FileNotFoundError):
            await store.sign_download(file, expires_at=datetime.now(UTC))
    finally:
        storages.register_backend(original._backend)


@pytest.mark.anyio
async def test_pdf_redirect_rechecks_membership_before_native_signing(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    reader = User(username="signed-reader", password_hash="unused")
    async_db.add(reader)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(
            workspace_id=item.workspace_id, user_id=reader.id, role=WorkspaceRole.viewer
        )
    )
    await async_db.commit()
    grant = await create_api_token(async_db, reader, "Signed PDF", expires_in_days=1)
    headers = {"Authorization": f"Bearer {grant.raw_token}"}
    calls = []

    async def sign(_self, path, *, expires_in=None, for_upload=False):
        await asyncio.sleep(0)
        calls.append((path, expires_in, for_upload))
        return "https://storage.example/signed.pdf"

    monkeypatch.setattr(get_object_store(), "_local_root", None)
    monkeypatch.setattr(ObstoreBackend, "sign_async", sign)
    base = f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}"
    try:
        # Private S3 endpoints use application streaming until direct delivery is enabled.
        streamed = await client.get(f"{base}/revisions/{revision.id}/content")
        assert streamed.status_code == 200 and streamed.content.startswith(b"%PDF")
        assert not calls
        monkeypatch.setenv("QUIREBASE_SIGNED_DOWNLOADS", "true")
        get_settings.cache_clear()
        response = await client.get(
            f"{base}/revisions/{revision.id}/content", follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "https://storage.example/signed.pdf"
        assert response.headers["cache-control"] == "private, no-store"
        assert calls == [(revision.file.path, 60, False)]
        wrong = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/items/{uuid4()}/revisions/{revision.id}/content",
            headers=headers,
        )
        assert wrong.status_code == 404 and len(calls) == 1
        membership = await async_db.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == item.workspace_id,
                WorkspaceMember.user_id == reader.id,
            )
        )
        membership.state = WorkspaceMemberState.suspended
        await async_db.commit()
        denied = await client.get(f"{base}/revisions/{revision.id}/content", headers=headers)
        assert denied.status_code == 404 and len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_export_signs_persisted_artifact_and_enforces_expiry(
    async_db, async_session_factory, fake_durable_operations, tmp_path, monkeypatch
):
    client, item, revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    calls = []
    user = await async_db.get(User, item.created_by)
    stored = await get_object_store().put_object(
        uuid4(), ObjectSuffix.PDF, b"%PDF-export", max_bytes=100
    )
    artifact = ExportArtifact(
        workspace_id=item.workspace_id,
        workflow_id="signed-export",
        file=FileObject(backend="documents", filename=stored.key, size=stored.size),
        expires_at=datetime.now(UTC) + timedelta(seconds=31),
    )
    async_db.add(artifact)
    await async_db.commit()
    workflow = SimpleNamespace(
        name=ANNOTATION_EXPORT_WORKFLOW,
        state="succeeded",
        attributes={"workspace_id": str(item.workspace_id), "actor_id": str(user.id)},
        output={"revision_id": revision.id, "object_key": "obsolete-checkpoint-key"},
    )

    async def get(_workflow_id):
        await asyncio.sleep(0)
        return workflow

    async def sign(_self, path, *, expires_in=None, for_upload=False):
        await asyncio.sleep(0)
        calls.append((path, expires_in, for_upload))
        return "https://storage.example/export.pdf"

    monkeypatch.setattr(fake_durable_operations, "get", get)
    monkeypatch.setenv("QUIREBASE_SIGNED_DOWNLOADS", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(get_object_store(), "_local_root", None)
    monkeypatch.setattr(ObstoreBackend, "sign_async", sign)
    try:
        target = await get_export_file(async_db, user, item.workspace_id, "signed-export")
        assert isinstance(target, SignedDownload)
        assert target.expires_at <= artifact.expires_at
        assert calls[0][0] == artifact.file.path and 1 <= calls[0][1] <= 30
        route = f"/api/v1/workspaces/{item.workspace_id}/annotation-exports/signed-export/content"
        response = await client.get(route, follow_redirects=False)
        assert (
            response.status_code == 307 and response.headers["cache-control"] == "private, no-store"
        )
        artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await async_db.commit()
        expired = await client.get(route)
        assert expired.status_code == 404 and len(calls) == 2
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_delayed_signing_cannot_outlive_artifact_expiry(monkeypatch):
    monkeypatch.setenv("QUIREBASE_SIGNED_DOWNLOADS", "true")
    get_settings.cache_clear()
    original = get_object_store()
    started = datetime.now(UTC)
    ticks = iter([started, started + timedelta(seconds=5)])

    async def sign(_self, path, *, expires_in=None, for_upload=False):
        await asyncio.sleep(0)
        return "https://storage.example/delayed.pdf"

    monkeypatch.setattr(ObstoreBackend, "sign_async", sign)
    monkeypatch.setattr(
        "quirebase.core.storage.datetime", SimpleNamespace(now=lambda _tz: next(ticks))
    )
    try:
        store = ObjectStore(
            S3Store(
                "quirebase-test",
                region="us-east-1",
                access_key_id="test-key",
                secret_access_key="test-secret",
            )
        )
        file = FileObject(backend="documents", filename="aa/bb/example.pdf", size=10)
        with pytest.raises(FileNotFoundError, match="download has expired"):
            await store.sign_download(file, expires_at=started + timedelta(seconds=31))
    finally:
        storages.register_backend(original._backend)
