"""Run the actual HTTP app, DBOS worker and local object store on a fresh scratch DB.

uv run --frozen python scripts/advanced_alchemy/use_cases.py
No configured database or credentials are used. Evidence contains no passwords or hashes.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


async def run(scratch: Path) -> dict:
    # Import only after main has selected the scratch configuration.
    import httpx2
    import pymupdf
    from advanced_alchemy.base import UUIDv7AuditBase
    from advanced_alchemy.config import AsyncSessionConfig, SQLAlchemyAsyncConfig
    from advanced_alchemy.mixins import AuditColumns
    from advanced_alchemy.types import GUID, FileObject, HashedPassword
    from advanced_alchemy.types.file_object.backends.obstore import ObstoreBackend
    from argon2 import PasswordHasher
    from sqlalchemy import bindparam, delete, func, select, text, update

    from quirebase.accounts import authentication
    from quirebase.audit import record_event
    from quirebase.core.crypto import hash_password_async
    from quirebase.core.database import AsyncSessionLocal, Base, engine
    from quirebase.core.passwords import password_backend
    from quirebase.core.storage import ObjectSuffix, get_object_store, object_key
    from quirebase.models import Attachment, AuditEvent, Item, Project, User, Workspace
    from quirebase.operations.maintenance import check_objects
    from quirebase.web.app import create_app

    evidence: dict = {
        "advanced_alchemy": "1.11.0",
        "runtime": "SQLite + LocalStore + real DBOS worker",
    }
    password = "prototype-password-2026"
    changed_password = "prototype-changed-2026"
    worker_log = (scratch / "worker.log").open("w")
    worker = None

    def start_worker():
        return subprocess.Popen(
            [str(Path(sys.executable).parent / "quirebase"), "worker"],
            cwd=ROOT,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
        )

    def stop_worker():
        if worker is not None:
            worker.terminate()
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)

    async def request(client, method, path, *, expected=200, **kwargs):
        response = await client.request(method, "/api/v1" + path, **kwargs)
        assert response.status_code == expected, (
            method,
            path,
            response.status_code,
            response.text[:500],
        )
        return response

    async def wait_workflow(client, workspace_id, workflow_id, state="succeeded"):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if worker is not None:
                assert worker.poll() is None, (scratch / "worker.log").read_text()[-2000:]
            status = (
                await request(client, "GET", f"/workspaces/{workspace_id}/workflows/{workflow_id}")
            ).json()
            if status["state"] in {"succeeded", "failed", "cancelled"}:
                assert status["state"] == state, status
                return status
            await asyncio.sleep(0.1)
        raise AssertionError(
            f"workflow did not finish: {workflow_id}; see {scratch / 'worker.log'}"
        )

    store = get_object_store()
    app = create_app()
    try:
        worker = start_worker()
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Origin": "http://testserver"},
            ) as client,
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers={"Origin": "http://testserver"},
            ) as outsider,
        ):
            await request(
                client,
                "POST",
                "/register",
                expected=201,
                json={"username": "aa-alice", "password": password},
            )
            login = (
                await request(
                    client, "POST", "/session", json={"username": "aa-alice", "password": password}
                )
            ).json()
            user_id = UUID(login["user"]["id"])
            workspace_id = UUID((await request(client, "GET", "/workspaces")).json()[0]["id"])
            prefix = f"/workspaces/{workspace_id}"
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                assert user is not None and isinstance(user.password_hash, HashedPassword)
                assert user.password_hash.verify(password)
                raw = await db.scalar(
                    text("SELECT password_hash FROM users WHERE id=:id").bindparams(
                        bindparam("id", type_=GUID())
                    ),
                    {"id": user_id},
                )
                assert password_backend.verify(password, raw)
                assert user_id.version == workspace_id.version == 7
                weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1).hash(password)
                user.password_hash = HashedPassword(weak, password_backend)
                await db.commit()
            await request(
                client,
                "POST",
                "/session",
                expected=401,
                json={"username": "aa-alice", "password": "wrong-password"},
            )
            async with AsyncSessionLocal() as db:
                assert (await db.get(User, user_id)).password_hash.hash_string == weak
            await request(
                client, "POST", "/session", json={"username": "aa-alice", "password": password}
            )
            async with AsyncSessionLocal() as db:
                hashed = (await db.get(User, user_id)).password_hash
                assert hashed.hash_string != weak and hashed.verify(password)
                assert not password_backend.needs_rehash(hashed.hash_string)
                # A controlled second connection writes a new password while login verifies.
                user = await db.get(User, user_id)
                user.password_hash = HashedPassword(weak, password_backend)
                await db.commit()
            original_verify = authentication.verify_and_update_password

            async def concurrent_change(encoded, supplied):
                result = await original_verify(encoded, supplied)
                async with AsyncSessionLocal() as other:
                    await other.execute(
                        update(User)
                        .where(User.id == user_id)
                        .values(password_hash=await hash_password_async(changed_password))
                    )
                    await other.commit()
                return result

            authentication.verify_and_update_password = concurrent_change
            try:
                await request(
                    client, "POST", "/session", json={"username": "aa-alice", "password": password}
                )
            finally:
                authentication.verify_and_update_password = original_verify
            async with AsyncSessionLocal() as db:
                assert (await db.get(User, user_id)).password_hash.verify(changed_password)
            await request(
                client,
                "PUT",
                "/account/password",
                json={"current_password": changed_password, "new_password": password},
            )
            await request(
                client, "POST", "/session", json={"username": "aa-alice", "password": password}
            )
            account = (await request(client, "GET", "/account")).json()
            assert "password" not in json.dumps(account)
            evidence["accounts"] = {
                "register_login_change": True,
                "single_hash_roundtrip": True,
                "wrong_password_no_rehash": True,
                "login_rehash": True,
                "rehash_does_not_overwrite_password_change": True,
                "private_projection": True,
                "entity_uuid_version": 7,
            }

            await request(
                outsider,
                "POST",
                "/register",
                expected=201,
                json={"username": "aa-bob", "password": password},
            )
            await request(
                outsider, "POST", "/session", json={"username": "aa-bob", "password": password}
            )
            outsider_workspace = (await request(outsider, "GET", "/workspaces")).json()[0]["id"]
            await request(
                outsider,
                "POST",
                f"/workspaces/{outsider_workspace}/items",
                expected=201,
                json={"title": "foreign secret"},
            )
            item_ids = []
            for i in range(27):
                result = (
                    await request(
                        client,
                        "POST",
                        prefix + "/items",
                        expected=201,
                        json={"title": f"Alchemy research {i:02d}"},
                    )
                ).json()
                item_ids.append(result["id"])
            item_id = item_ids[0]
            first = (await request(client, "GET", prefix + "/items")).json()
            second = (await request(client, "GET", prefix + "/items?page=2")).json()
            empty = (await request(client, "GET", prefix + "/items?page=999")).json()
            filtered = (await request(client, "GET", prefix + "/items?query=foreign")).json()
            assert first["total"] == second["total"] == empty["total"] == 27
            assert len(first["items"]) == 25 and len(second["items"]) == 2 and empty["items"] == []
            assert filtered["total"] == 0
            assert {row["id"] for row in first["items"]}.isdisjoint(
                row["id"] for row in second["items"]
            )
            await request(outsider, "GET", prefix + "/items", expected=404)
            async with AsyncSessionLocal() as db:
                user = await db.get(User, user_id)
                user.role = "administrator"
                await db.commit()
            users = (await request(client, "GET", "/admin/users?page=999")).json()
            assert users["total"] == 2 and users["users"] == []
            await request(outsider, "GET", "/admin/users", expected=404)
            evidence["pagination"] = {
                "actual_item_repository": True,
                "first_second_empty_lengths": [25, 2, 0],
                "empty_page_total": 27,
                "workspace_filter_before_count": True,
                "actual_user_repository_empty_total": 2,
                "authorization_preserved": True,
            }

            async with AsyncSessionLocal() as db:
                item = await db.get(Item, item_id)
                original_created, original_updated = item.created_at, item.updated_at
            await request(
                client,
                "PUT",
                prefix + f"/items/{item_id}",
                json={"expected_version": 1, "metadata": {"title": "Alchemy revised"}},
            )
            async with AsyncSessionLocal() as db:
                item = await db.get(Item, item_id)
                assert item.created_at == original_created and item.updated_at > original_updated
                assert item.updated_at.tzinfo == UTC
                after_api = item.updated_at
                await db.execute(
                    update(Item).where(Item.id == item_id).values(title="Alchemy SQL update")
                )
                await db.commit()
                await db.refresh(item)
                assert item.updated_at > after_api
                override = datetime.now(UTC) - timedelta(days=1)
                await db.execute(update(Item).where(Item.id == item_id).values(updated_at=override))
                await db.commit()
                await db.refresh(item)
                assert item.updated_at == override
                baseline_events = await db.scalar(select(func.count()).select_from(AuditEvent))
                item.title = "Rolled back"
                record_event(
                    db, user_id, "prototype.rollback", "item", item_id, workspace_id=workspace_id
                )
                await db.flush()
                await db.rollback()
                await db.refresh(item)
                assert item.title == "Alchemy SQL update" and item.updated_at == override
                assert (
                    await db.scalar(select(func.count()).select_from(AuditEvent)) == baseline_events
                )
            assert all(issubclass(model, AuditColumns) for model in (Workspace, Item, Project))
            evidence["audit_mixin"] = {
                "models": sum(
                    issubclass(mapper.class_, UUIDv7AuditBase) for mapper in Base.registry.mappers
                ),
                "base": "UUIDv7AuditBase",
                "sqlite_uuid_storage": "BLOB (16 bytes)",
                "postgres_uuid_storage": "UUID",
                "api_mutation_touches_updated_at": True,
                "created_at_stable": True,
                "sql_update_touches_updated_at": True,
                "explicit_timestamp_preserved": True,
                "utc_roundtrip": True,
                "entity_and_business_audit_rollback_together": True,
                "global_touch_listener_enabled": False,
            }

            # Stop the worker: upload object and durable receipt survive a later restart.
            stop_worker()
            worker = None
            payload = b"complete-use-case attachment\n" * 3
            receipt = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/attachments",
                    expected=202,
                    files={"attachment": ("results.txt", payload, "text/plain")},
                )
            ).json()
            worker = start_worker()
            await wait_workflow(client, workspace_id, receipt["id"])
            async with AsyncSessionLocal() as db:
                attachment = await db.scalar(
                    select(Attachment).where(Attachment.item_id == item_id)
                )
                attachment_id = attachment.id
                key = attachment.file.path
                assert attachment.file.size == len(payload)
                assert attachment.file.metadata["original_name"] == "results.txt"
                assert attachment.file.content_type == "text/plain"
                assert await check_objects(db) == []
            docs = (await request(client, "GET", prefix + f"/items/{item_id}/documents")).json()
            assert docs["files"][0]["original_name"] == "results.txt" and docs["files"][0][
                "size"
            ] == len(payload)
            content_path = prefix + f"/items/{item_id}/attachments/{attachment_id}/content"
            content = await request(client, "GET", content_path)
            assert content.content == payload
            await request(
                client,
                "GET",
                content_path,
                expected=304,
                headers={"If-None-Match": content.headers["etag"]},
            )
            await request(outsider, "GET", content_path, expected=404)
            archive = await request(
                client, "GET", prefix + f"/items/{item_id}/archive?include_supplements=true"
            )
            with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
                assert payload in [bundle.read(name) for name in bundle.namelist()]
            target = (
                await request(
                    client,
                    "POST",
                    "/workspaces",
                    expected=201,
                    json={"name": "AA copy target", "owner_username": "aa-alice"},
                )
            ).json()["id"]
            copied = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/copy",
                    expected=201,
                    json={"target_workspace_id": target},
                )
            ).json()
            async with AsyncSessionLocal() as db:
                copy_attachment = await db.scalar(
                    select(Attachment).where(Attachment.item_id == copied["target_item_id"])
                )
                assert copy_attachment.file.path != key and copy_attachment.file.size == len(
                    payload
                )
                copied_content = await store.get(copy_attachment.file.path)
                assert b"".join([chunk async for chunk in copied_content.body]) == payload
            evidence["attachments"] = {
                "real_worker_restart_recovery": True,
                "stored_object_is_canonical_metadata": True,
                "document_projection": True,
                "download_and_etag": True,
                "authorization": True,
                "archive": True,
                "cross_workspace_copy_has_independent_object": True,
                "integrity_check": True,
            }

            # Exercise the shared AA upload backend with PDF processing and ranged reads.
            pdf = pymupdf.open()
            pdf.new_page().insert_text((72, 72), "Advanced Alchemy actual PDF workflow")
            pdf_bytes = pdf.tobytes()
            pdf.close()
            revision_receipt = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/revisions",
                    expected=202,
                    files={"pdf": ("paper.pdf", pdf_bytes, "application/pdf")},
                )
            ).json()
            await wait_workflow(client, workspace_id, revision_receipt["id"])
            files = (await request(client, "GET", prefix + f"/items/{item_id}/documents")).json()[
                "files"
            ]
            revision = next(file for file in files if file["kind"] == "revision")
            pdf_path = prefix + f"/items/{item_id}/revisions/{revision['id']}/content"
            ranged = await request(
                client, "GET", pdf_path, expected=206, headers={"Range": "bytes=0-4"}
            )
            assert ranged.content == b"%PDF-"
            assert (await request(client, "GET", pdf_path)).content == pdf_bytes
            await request(
                client, "GET", prefix + f"/items/{item_id}/revisions/{revision['id']}/thumbnail"
            )
            annotation_id, reply_id = str(uuid4()), str(uuid4())
            annotation_path = prefix + f"/items/{item_id}/annotations/{annotation_id}"
            created_annotation = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/annotations",
                    expected=201,
                    json={
                        "id": annotation_id,
                        "revision_id": revision["id"],
                        "page_index": 0,
                        "kind": "note",
                        "scope": "private",
                        "body": "Native UUID lineage",
                        "payload": {
                            "type": "note",
                            "rect": {"x": 72, "y": 72, "width": 20, "height": 20},
                        },
                    },
                )
            ).json()
            assert created_annotation["id"] == annotation_id
            created_reply = (
                await request(
                    client,
                    "POST",
                    annotation_path + "/replies",
                    expected=201,
                    json={"id": reply_id, "body": "Real API reply"},
                )
            ).json()
            assert created_reply["id"] == reply_id
            annotations = (
                await request(
                    client,
                    "GET",
                    prefix + f"/items/{item_id}/annotations",
                    params={"revision_id": revision["id"], "pagination": "cursor", "per_page": 1},
                )
            ).json()
            assert (
                annotations["total"] == 1 and annotations["annotations"][0]["id"] == annotation_id
            )
            exported = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/annotation-exports",
                    expected=202,
                    json={
                        "revision_id": revision["id"],
                        "include_private": True,
                        "timezone": "UTC",
                    },
                )
            ).json()
            await wait_workflow(client, workspace_id, exported["id"])
            export_path = prefix + f"/annotation-exports/{exported['id']}"
            assert (await request(client, "GET", export_path)).json()["state"] == "succeeded"
            annotated_pdf = await request(client, "GET", export_path + "/content")
            with pymupdf.open(stream=annotated_pdf.content, filetype="pdf") as document:
                notes = list(document[0].annots())
                assert any(note.info["content"].startswith("Native UUID lineage") for note in notes)
            await request(outsider, "GET", export_path + "/content", expected=404)
            evidence["annotations"] = {
                "client_uuid4_identity_preserved": True,
                "native_uuid_foreign_keys": True,
                "reply_api": True,
                "cursor_pagination": True,
                "real_worker_export_and_download": True,
                "requester_only_export": True,
            }
            invalid = (
                await request(
                    client,
                    "POST",
                    prefix + f"/items/{item_id}/attachments",
                    expected=202,
                    files={"attachment": ("bad.png", b"not a PNG", "image/png")},
                    data={"graphical_abstract": "true"},
                )
            ).json()
            await wait_workflow(client, workspace_id, invalid["id"], state="failed")
            async with AsyncSessionLocal() as db:
                assert await check_objects(db) == []
            evidence["pdf"] = {
                "shared_aa_upload_backend": True,
                "real_processing_workflow": True,
                "full_and_range_reads": True,
                "thumbnail": True,
                "invalid_image_workflow_cleans_object": True,
            }

            await request(
                client, "DELETE", prefix + f"/items/{item_id}/attachments/{attachment_id}"
            )
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if not await store.exists(key):
                    break
                await asyncio.sleep(0.1)
            assert not await store.exists(key)
            evidence["attachments"]["delete_owned_object"] = True

            # Probe AA's default post-commit listener with an actual Attachment mapping.
            # This listener gets its own sessionmaker and cannot affect the app sessions.
            started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

            class FailingBackend(ObstoreBackend):
                async def save_object_async(self, file_object, data, **kwargs):
                    started.set()
                    await release.wait()
                    finished.set()
                    raise OSError("injected storage failure")

            failing = FailingBackend(key="documents", fs=store._backend.fs)
            config = SQLAlchemyAsyncConfig(
                engine_instance=engine,
                metadata=Base.metadata,
                session_config=AsyncSessionConfig(expire_on_commit=False),
                enable_file_object_listener=True,
                enable_touch_updated_timestamp_listener=False,
            )
            listener_sessions = config.create_session_maker()
            failed_id = uuid4()
            failed_key = object_key(uuid4(), ObjectSuffix.BINARY)
            async with listener_sessions() as db:
                descriptor = FileObject(
                    backend=failing,
                    filename=failed_key,
                    size=4,
                    content=b"data",
                    metadata={"original_name": "failure.bin"},
                )
                db.add(
                    Attachment(
                        id=failed_id,
                        workspace_id=workspace_id,
                        item_id=item_id,
                        created_by=user_id,
                        file=descriptor,
                    )
                )
                await db.commit()
                await asyncio.wait_for(started.wait(), 5)
                async with AsyncSessionLocal() as observer:
                    assert await observer.get(Attachment, failed_id) is not None
                    assert not await store.exists(failed_key)
                release.set()
                await asyncio.wait_for(finished.wait(), 5)
                await asyncio.sleep(0.05)
            async with AsyncSessionLocal() as db:
                assert await db.get(Attachment, failed_id) is not None
                assert not await store.exists(failed_key)
                await db.execute(delete(Attachment).where(Attachment.id == failed_id))
                await db.commit()
            evidence["default_file_listener"] = {
                "commit_returns_before_file_save": True,
                "row_visible_while_upload_blocked": True,
                "upload_failure_leaves_committed_row": True,
                "app_listener_enabled": False,
            }
    finally:
        stop_worker()
        worker_log.close()
        await engine.dispose()
    return evidence


def main():
    scratch = Path(tempfile.mkdtemp(prefix="quirebase-aa-PROTOTYPE-", dir="/private/tmp"))
    os.environ.update({
        "QUIREBASE_DATABASE_URL": f"sqlite:///{scratch / 'prototype.db'}",
        "QUIREBASE_DATA_DIR": str(scratch / "data"),
        "QUIREBASE_REGISTRATION_POLICY": "open",
        "QUIREBASE_LOG_LEVEL": "WARNING",
        "FASTAPI_ENV": "development",
    })
    cli = str(Path(sys.executable).parent / "quirebase")
    subprocess.run([cli, "init-db"], cwd=ROOT, check=True, capture_output=True, text=True)
    evidence = asyncio.run(run(scratch))
    doctor = subprocess.run([cli, "doctor"], cwd=ROOT, check=True, capture_output=True, text=True)
    evidence["fresh_initial_migration_doctor"] = doctor.stdout.strip().splitlines()
    (HERE / "use_case_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(f"Scratch database and worker log: {scratch}")


if __name__ == "__main__":
    main()
