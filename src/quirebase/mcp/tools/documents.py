from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from quirebase.documents import (
    AnnotationCreate,
    AnnotationPayload,
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationUpdate,
    create_annotation_reply,
    create_document_annotation,
    delete_annotation_reply,
    delete_document_annotation,
    list_document_annotations,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.library import FilesWorkspace, WorkspaceSection, open_item_workspace
from quirebase.mcp.tools.annotations import DESTRUCTIVE, READ_ONLY, WRITE
from quirebase.programmatic import (
    AnnotationReplyView,
    AnnotationView,
    DocumentListView,
    document_list_view,
)

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.mcp.runtime import McpRuntime


def register_document_tools(server: MCPServer, runtime: McpRuntime) -> None:
    @server.tool(
        name="documents.list",
        description="List revision and attachment metadata for a visible Item; no file bytes or text.",
        annotations=READ_ONLY,
    )
    async def documents_list(item_id: str) -> DocumentListView:
        async def run(db, user):
            workspace = await open_item_workspace(db, user, item_id, WorkspaceSection.files)
            if not isinstance(workspace, FilesWorkspace):  # pragma: no cover
                return DocumentListView(item_id=item_id, files=[])
            return document_list_view(item_id, workspace)

        return await runtime.call("documents.list", run, conceal_resource="item not found")

    @server.tool(
        name="annotations.list",
        description="List private annotations and optionally visible annotations for one Project.",
        annotations=READ_ONLY,
    )
    async def annotations_list(
        item_id: str, revision_id: str, project_id: str | None = None
    ) -> list[AnnotationView]:
        rows = await runtime.call(
            "annotations.list",
            lambda db, user: list_document_annotations(db, user, item_id, revision_id, project_id),
            conceal_resource="document not found",
        )
        return [AnnotationView.model_validate(row) for row in rows]

    @server.tool(
        name="annotations.create",
        description="Create a private or Project-visible PDF annotation.",
        annotations=WRITE,
    )
    async def annotations_create(
        item_id: str,
        id: str,
        revision_id: str,
        page_index: int,
        kind: Literal[
            "highlight",
            "underline",
            "strikeout",
            "note",
            "free_text",
            "ink",
            "rectangle",
            "ellipse",
            "line",
            "arrow",
        ],
        payload: AnnotationPayload,
        scope: Literal["private", "project"] = "private",
        project_id: str | None = None,
        body: str | None = None,
        selected_text: str | None = None,
    ) -> AnnotationView:
        async def run(db, user):
            data = AnnotationCreate.model_validate({
                "id": id,
                "revision_id": revision_id,
                "page_index": page_index,
                "kind": kind,
                "payload": payload,
                "scope": scope,
                "project_id": project_id,
                "body": body,
                "selected_text": selected_text,
            })
            return AnnotationView.model_validate(
                await create_document_annotation(db, user, item_id, data)
            )

        return await runtime.call(
            "annotations.create",
            run,
            conceal_resource="document not found",
        )

    @server.tool(
        name="annotations.update",
        description="Update an editable annotation using optimistic version checking.",
        annotations=WRITE,
    )
    async def annotations_update(
        item_id: str,
        annotation_id: str,
        version: int,
        page_index: int,
        kind: Literal[
            "highlight",
            "underline",
            "strikeout",
            "note",
            "free_text",
            "ink",
            "rectangle",
            "ellipse",
            "line",
            "arrow",
        ],
        payload: AnnotationPayload,
        scope: Literal["private", "project"],
        project_id: str | None = None,
        body: str | None = None,
        selected_text: str | None = None,
    ) -> AnnotationView:
        async def run(db, user):
            data = AnnotationUpdate.model_validate({
                "version": version,
                "page_index": page_index,
                "kind": kind,
                "payload": payload,
                "scope": scope,
                "project_id": project_id,
                "body": body,
                "selected_text": selected_text,
            })
            return AnnotationView.model_validate(
                await update_document_annotation(db, user, item_id, annotation_id, data)
            )

        return await runtime.call(
            "annotations.update",
            run,
            conceal_resource="annotation not found",
        )

    @server.tool(
        name="annotations.delete",
        description="Soft-delete an annotation editable by the authenticated User.",
        annotations=DESTRUCTIVE,
    )
    async def annotations_delete(item_id: str, annotation_id: str, version: int) -> dict[str, bool]:
        await runtime.call(
            "annotations.delete",
            lambda db, user: delete_document_annotation(db, user, item_id, annotation_id, version),
            conceal_resource="annotation not found",
        )
        return {"ok": True}

    @server.tool(
        name="annotation_replies.create",
        description="Reply to a visible PDF annotation.",
        annotations=WRITE,
    )
    async def annotation_replies_create(
        item_id: str, annotation_id: str, id: str, body: str
    ) -> AnnotationReplyView:
        async def run(db, user):
            data = AnnotationReplyCreate.model_validate({"id": id, "body": body})
            return AnnotationReplyView.model_validate(
                await create_annotation_reply(db, user, item_id, annotation_id, data)
            )

        return await runtime.call(
            "annotation_replies.create", run, conceal_resource="annotation not found"
        )

    @server.tool(
        name="annotation_replies.update",
        description="Update an editable Annotation Reply using optimistic version checking.",
        annotations=WRITE,
    )
    async def annotation_replies_update(
        item_id: str, annotation_id: str, reply_id: str, version: int, body: str
    ) -> AnnotationReplyView:
        async def run(db, user):
            data = AnnotationReplyUpdate.model_validate({"version": version, "body": body})
            return AnnotationReplyView.model_validate(
                await update_annotation_reply(db, user, item_id, annotation_id, reply_id, data)
            )

        return await runtime.call(
            "annotation_replies.update", run, conceal_resource="annotation reply not found"
        )

    @server.tool(
        name="annotation_replies.delete",
        description="Soft-delete an editable Annotation Reply.",
        annotations=DESTRUCTIVE,
    )
    async def annotation_replies_delete(
        item_id: str, annotation_id: str, reply_id: str, version: int
    ) -> dict[str, bool]:
        await runtime.call(
            "annotation_replies.delete",
            lambda db, user: delete_annotation_reply(
                db, user, item_id, annotation_id, reply_id, version
            ),
            conceal_resource="annotation reply not found",
        )
        return {"ok": True}
