from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app_helpers import authenticated_async_client
from sqlalchemy import event, func, select
from workspace_helpers import provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.core.errors import PermissionDenied
from quirebase.library import (
    AuthorFilter,
    BatchConflict,
    ImportBatchUnavailable,
    LibraryFilter,
    commit_import_batch,
    create_item,
    delete_import_batch,
    delete_item,
    get_import_batch_preview,
    get_library_facets,
    search_library,
    stage_import_batch,
)
from quirebase.models import (
    ImportBatch,
    Item,
    ItemTag,
    LoginSession,
    Project,
    ProjectItem,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

pytestmark = pytest.mark.anyio


def _work(title: str, year: str = "2025", kind: str = "JournalArticle") -> dict:
    return {
        "id": f"urn:uuid:{uuid4()}",
        "type": kind,
        "title": title,
        "date_published": year,
        "container": {"title": "Import journal"},
        "contributors": [
            {"type": "Person", "person": {"family_name": "Smith"}, "roles": ["Author"]}
        ],
        "subjects": [{"subject": "Quantum"}],
    }


async def _stage(db, actor, workspace_id, values):
    return await stage_import_batch(
        db, actor, workspace_id, json.dumps(values).encode(), "commonmeta"
    )


async def test_import_receipts_recover_over_http_and_keep_original_ids_after_deletion(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, existing, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = existing.workspace_id
    base = f"/api/v1/workspaces/{workspace_id}"
    try:
        preview = await client.post(
            f"{base}/imports/bibliography",
            data={"file_format": "commonmeta"},
            files={
                "bibliography": (
                    "batch.json",
                    json.dumps([_work("Imported alpha"), _work("Imported beta")]).encode(),
                    "application/json",
                )
            },
        )
        assert preview.status_code == 201, preview.text
        batch_id = preview.json()["id"]
        assert preview.json()["committed_item_ids"] == []
        assert len(preview.json()["records"]) == 2

        committed = await client.post(f"{base}/imports/{batch_id}/commit")
        assert committed.status_code == 200, committed.text
        item_ids = committed.json()["committed_item_ids"]
        assert len(item_ids) == 2 and str(existing.id) not in item_ids
        assert all(UUID(item_id) for item_id in item_ids)
        assert committed.json() == {
            **preview.json(),
            "status": "committed",
            "workflow_id": None,
            "records": [],
            "errors": [],
            "committed_item_ids": item_ids,
        }
        for _ in range(2):
            receipt = await client.get(f"{base}/imports/{batch_id}")
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()["status"] == "committed"
            assert receipt.json()["records"] == []
            assert receipt.json()["committed_item_ids"] == item_ids
            assert receipt.json() == committed.json()
            assert "object_key" not in receipt.text and "_source_id" not in receipt.text
            replayed = await client.post(f"{base}/imports/{batch_id}/commit")
            assert replayed.json() == committed.json()
        assert await db.scalar(select(func.count(Item.id))) == 3

        actor = await db.get(User, existing.created_by)
        for remaining, item_id in zip((1, 0), item_ids, strict=True):
            await delete_item(db, actor, workspace_id, UUID(item_id))
            result = await client.get(f"{base}/items", params={"import_batch": batch_id})
            assert result.status_code == 200, result.text
            assert result.json()["total"] == remaining
            assert all(row["id"] in item_ids for row in result.json()["items"])
        facets = await client.get(f"{base}/items/facets", params={"import_batch": batch_id})
        assert facets.json() == {"authors": [], "keywords": [], "reference_types": []}
        assert (await client.get(f"{base}/imports/{batch_id}")).json()[
            "committed_item_ids"
        ] == item_ids
        assert (await client.post(f"{base}/imports/{batch_id}/commit")).json() == committed.json()
    finally:
        await client.aclose()
        get_settings.cache_clear()


async def test_readonly_import_library_intersects_search_project_tag_and_metadata_filters(
    persistence_db,
):
    db = persistence_db
    owner = User(username=f"import-owner-{uuid4()}", password_hash="unused")
    viewer = User(username=f"import-viewer-{uuid4()}", password_hash="unused")
    db.add_all([owner, viewer])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role=WorkspaceRole.viewer))
    await db.commit()
    preview = await _stage(
        db,
        owner,
        workspace.id,
        [
            _work("Imported alpha", "2024"),
            _work("Imported beta"),
            _work("Imported book", kind="Book"),
        ],
    )
    item_ids = (await commit_import_batch(db, owner, workspace.id, preview.id)).committed_item_ids
    outsider = await create_item(db, owner, workspace.id, _work("Imported outsider"))
    project = Project(workspace_id=workspace.id, created_by=owner.id, name="Import reading")
    tag = Tag(workspace_id=workspace.id, name="Reading", created_by=owner.id)
    db.add_all([project, tag])
    await db.flush()
    for item_id in [*item_ids, outsider.item_id]:
        db.add(ItemTag(workspace_id=workspace.id, item_id=item_id, tag_id=tag.id))
        db.add(
            ProjectItem(
                workspace_id=workspace.id,
                project_id=project.id,
                item_id=item_id,
                added_by=owner.id,
            )
        )
    await db.commit()

    rows, total = await search_library(
        db,
        viewer,
        workspace.id,
        LibraryFilter(import_batch=preview.id),
        sort="title",
        limit=1,
        offset=1,
    )
    assert total == 3 and [row.id for row in rows] == [item_ids[1]]
    page_facets = await get_library_facets(
        db,
        viewer,
        workspace.id,
        LibraryFilter(import_batch=preview.id),
        sort="title",
        limit=1,
        offset=2,
    )
    assert [(row.value, row.item_count) for row in page_facets.reference_types] == [("Book", 1)]
    filters = {
        "import_batch": preview.id,
        "q": "Imported",
        "tag": tag.id,
        "project": project.id,
        "year": "2025",
        "reference_type": "JournalArticle",
        "publication_title": "Import journal",
        "author": "Smith",
        "keyword": "Quan",
        "keyword_exact": "Quantum",
        "has_files": False,
        "authors": (AuthorFilter("Smith", ""),),
    }
    rows, total = await search_library(db, viewer, workspace.id, LibraryFilter(**filters))
    assert total == 1 and [row.id for row in rows] == [item_ids[1]]
    facets = await get_library_facets(db, viewer, workspace.id, LibraryFilter(**filters))
    assert [(row.last_name, row.item_count) for row in facets.authors] == [("Smith", 1)]
    assert [(row.value, row.item_count) for row in facets.keywords] == [("Quantum", 1)]
    assert [(row.value, row.item_count) for row in facets.reference_types] == [
        ("JournalArticle", 1)
    ]
    receipt = await get_import_batch_preview(db, viewer, workspace.id, preview.id)
    assert receipt.committed_item_ids == tuple(item_ids)
    with pytest.raises(PermissionDenied):
        await commit_import_batch(db, viewer, workspace.id, preview.id)


async def test_large_import_receipt_filters_in_database_without_per_item_parameters(
    persistence_db,
):
    db = persistence_db
    actor = User(username=f"import-large-{uuid4()}", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    imported = await create_item(db, actor, workspace.id, _work("Imported large receipt"))
    await create_item(db, actor, workspace.id, _work("Unrelated Item"))
    # Most Items from a large import may since have been deleted. Its immutable
    # receipt still exceeds PostgreSQL drivers' parameter limits if expanded into IN.
    receipt = [str(uuid4()) for _ in range(70_000)]
    receipt.extend([str(imported.item_id), str(imported.item_id)])
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=actor.id,
        file_format="commonmeta",
        status="committed",
        records=[],
        errors=[],
        committed_item_ids=receipt,
    )
    db.add(batch)
    await db.commit()
    parameter_counts = []

    def capture_parameters(_connection, _cursor, _statement, parameters, _context, _many):
        parameter_counts.append(len(parameters))
        assert len(parameters) < 1000, "receipt Items must not become individual SQL parameters"

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", capture_parameters)
    try:
        rows, total = await search_library(
            db, actor, workspace.id, LibraryFilter(import_batch=batch.id)
        )
        assert total == 1 and [row.id for row in rows] == [imported.item_id]
        facets = await get_library_facets(
            db, actor, workspace.id, LibraryFilter(import_batch=batch.id)
        )
        assert [(row.last_name, row.item_count) for row in facets.authors] == [("Smith", 1)]
        assert [(row.value, row.item_count) for row in facets.keywords] == [("Quantum", 1)]
        assert [(row.value, row.item_count) for row in facets.reference_types] == [
            ("JournalArticle", 1)
        ]
        assert parameter_counts
    finally:
        event.remove(engine, "before_cursor_execute", capture_parameters)


@pytest.mark.parametrize("status", ["ready", "pending", "failed"])
async def test_uncommitted_import_scope_is_unavailable_to_search_and_facets(persistence_db, status):
    db = persistence_db
    actor = User(username=f"import-uncommitted-{uuid4()}", password_hash="unused")
    db.add(actor)
    await db.flush()
    workspace = await provision_initial_workspace(db, actor)
    batch = ImportBatch(
        workspace_id=workspace.id,
        actor_id=actor.id,
        file_format="metadata",
        status=status,
        records=[],
        errors=[],
        committed_item_ids=[str(uuid4())],
    )
    db.add(batch)
    await db.commit()
    assert (
        await get_import_batch_preview(db, actor, workspace.id, batch.id)
    ).committed_item_ids == ()
    with pytest.raises(BatchConflict, match="has not been committed"):
        await search_library(
            db, actor, workspace.id, LibraryFilter(import_batch=batch.id, q="no results")
        )
    with pytest.raises(BatchConflict, match="has not been committed"):
        await get_library_facets(db, actor, workspace.id, LibraryFilter(import_batch=batch.id))


async def test_import_scope_http_validates_batch_lineage_and_state_for_readonly_members(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = item.workspace_id
    base = f"/api/v1/workspaces/{workspace_id}"
    actor = await db.get(User, item.created_by)
    batch = await _stage(db, actor, workspace_id, [_work("Scoped imported")])
    imported_ids = (await commit_import_batch(db, actor, workspace_id, batch.id)).committed_item_ids
    viewer = User(username="import-http-viewer", password_hash="unused")
    other_workspace = Workspace(name="Other import Workspace", created_by=actor.id)
    db.add_all([viewer, other_workspace])
    await db.flush()
    db.add_all([
        WorkspaceMember(workspace_id=workspace_id, user_id=viewer.id, role=WorkspaceRole.viewer),
        WorkspaceMember(
            workspace_id=other_workspace.id, user_id=viewer.id, role=WorkspaceRole.viewer
        ),
        WorkspaceMember(
            workspace_id=other_workspace.id, user_id=actor.id, role=WorkspaceRole.owner
        ),
        LoginSession(
            token_hash=token_hash("import-viewer-session"),
            user_id=viewer.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
    ])
    foreign = ImportBatch(
        workspace_id=other_workspace.id,
        actor_id=actor.id,
        file_format="metadata",
        status="committed",
        records=[],
        errors=[],
        committed_item_ids=[str(item_id) for item_id in imported_ids],
    )
    uncommitted = [
        ImportBatch(
            workspace_id=workspace_id,
            actor_id=actor.id,
            file_format="metadata",
            status=status,
            records=[],
            errors=[],
        )
        for status in ("ready", "pending", "failed")
    ]
    db.add_all([foreign, *uncommitted])
    await db.commit()
    client.cookies.set(get_settings().session_cookie, "import-viewer-session")
    try:
        rows = await client.get(f"{base}/items", params={"import_batch": str(batch.id)})
        assert rows.status_code == 200, rows.text
        assert [row["id"] for row in rows.json()["items"]] == list(map(str, imported_ids))
        facets = await client.get(
            f"{base}/items/facets",
            params={"import_batch": str(batch.id), "keyword_exact": "Quantum"},
        )
        assert facets.status_code == 200, facets.text
        assert facets.json()["keywords"] == [{"value": "Quantum", "item_count": 1}]
        receipt = await client.get(f"{base}/imports/{batch.id}")
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["committed_item_ids"] == list(map(str, imported_ids))
        assert (await client.post(f"{base}/imports/{batch.id}/commit")).status_code == 403
        for path in ("items", "items/facets"):
            for scope in (uuid4(), foreign.id):
                response = await client.get(f"{base}/{path}", params={"import_batch": str(scope)})
                assert response.status_code == 404, response.text
                assert response.json() == {
                    "code": "import_batch_unavailable",
                    "message": "Import Batch not found",
                }
            for pending in uncommitted:
                response = await client.get(
                    f"{base}/{path}", params={"import_batch": str(pending.id)}
                )
                assert response.status_code == 409, response.text
                assert response.json()["code"] == "import_batch_conflict"
        # A foreign receipt cannot widen even an authorized Workspace's Item read model.
        rows = await client.get(
            f"/api/v1/workspaces/{other_workspace.id}/items",
            params={"import_batch": str(foreign.id)},
        )
        assert rows.status_code == 200 and rows.json()["items"] == []
        with pytest.raises(ImportBatchUnavailable):
            await search_library(db, viewer, workspace_id, LibraryFilter(import_batch=foreign.id))
        for scope in (uuid4(), foreign.id):
            response = await client.get(f"{base}/imports/{scope}")
            assert response.status_code == 404, response.text
            assert response.json() == {
                "code": "import_batch_unavailable",
                "message": "Import Batch not found",
            }
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.parametrize("path", ["items", "items/facets"])
async def test_combined_import_project_filters_distinguish_receipt_and_project_unavailability(
    async_db, async_session_factory, tmp_path, monkeypatch, path
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_id = item.workspace_id
    base = f"/api/v1/workspaces/{workspace_id}"
    owner = await db.get(User, item.created_by)
    preview = await _stage(db, owner, workspace_id, [_work("Imported reading context")])
    receipt = await commit_import_batch(db, owner, workspace_id, preview.id)
    viewer = User(username="combined-import-viewer", password_hash="unused")
    project = Project(workspace_id=workspace_id, created_by=owner.id, name="Visible Project")
    managed = Project(
        workspace_id=workspace_id,
        created_by=owner.id,
        name="Hidden Project",
        participation="managed",
    )
    db.add_all([viewer, project, managed])
    await db.flush()
    db.add_all([
        WorkspaceMember(workspace_id=workspace_id, user_id=viewer.id, role=WorkspaceRole.viewer),
        LoginSession(
            token_hash=token_hash("combined-import-session"),
            user_id=viewer.id,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        ProjectItem(
            workspace_id=workspace_id,
            project_id=project.id,
            item_id=receipt.committed_item_ids[0],
            added_by=owner.id,
        ),
    ])
    await db.commit()
    client.cookies.set(get_settings().session_cookie, "combined-import-session")
    try:
        filters = {"project": str(project.id), "import_batch": str(receipt.id)}
        response = await client.get(f"{base}/{path}", params=filters)
        assert response.status_code == 200, response.text
        assert response.json()["total" if path == "items" else "authors"]

        # Valid receipts must not mask loss of Project visibility or a missing Project.
        for unavailable_project in (managed.id, uuid4()):
            response = await client.get(
                f"{base}/{path}", params={**filters, "project": str(unavailable_project)}
            )
            assert response.status_code == 404, response.text
            assert response.json() == {"code": "not_found", "message": "not found"}

        await delete_import_batch(db, owner, workspace_id, receipt.id)
        response = await client.get(f"{base}/{path}", params=filters)
        assert response.status_code == 404, response.text
        assert response.json() == {
            "code": "import_batch_unavailable",
            "message": "Import Batch not found",
        }

        # Deleting the receipt preserves the Project's Items and metadata facets.
        response = await client.get(f"{base}/{path}", params={"project": str(project.id)})
        assert response.status_code == 200, response.text
        assert response.json()["total" if path == "items" else "authors"]
    finally:
        await client.aclose()
        get_settings.cache_clear()
