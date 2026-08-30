from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from quirebase.documents import (
    AnnotationCreate,
    AnnotationUpdate,
    SegmentInput,
    create_document_annotation,
    delete_document_annotation,
    list_document_annotations,
    update_document_annotation,
)
from quirebase.library import FilesWorkspace, WorkspaceSection, open_item_workspace
from quirebase.mcp.tools.annotations import DESTRUCTIVE, READ_ONLY, WRITE
from quirebase.programmatic import AnnotationView, DocumentListView, document_list_view

if TYPE_CHECKING:
    from mcp.server import MCPServer

    from quirebase.mcp.runtime import McpRuntime


def register_document_tools(server: MCPServer, runtime: McpRuntime) -> None:
    @server.tool(
        name="documents.list",
        description="List revision and attachment metadata for a visible Item; no file bytes or text.",
        annotations=READ_ONLY,
    )
    def documents_list(item_id: str) -> DocumentListView:
        def run(db, user):
            workspace = open_item_workspace(db, user, item_id, WorkspaceSection.files)
            if not isinstance(workspace, FilesWorkspace):  # pragma: no cover
                return DocumentListView(item_id=item_id, files=[])
            return document_list_view(item_id, workspace)

        return runtime.call("documents.list", run, conceal_resource="item not found")

    @server.tool(
        name="annotations.list",
        description="List private annotations and optionally visible annotations for one Project.",
        annotations=READ_ONLY,
    )
    def annotations_list(
        item_id: str, revision_id: str, project_id: str | None = None
    ) -> list[AnnotationView]:
        rows = runtime.call(
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
    def annotations_create(
        item_id: str,
        revision_id: str,
        kind: Literal["highlight", "underline", "note"],
        segments: list[SegmentInput],
        scope: Literal["private", "project"] = "private",
        project_id: str | None = None,
        color: Literal["yellow", "green", "blue", "red"] = "yellow",
        body: str | None = None,
        selected_text: str | None = None,
    ) -> AnnotationView:
        def run(db, user):
            data = AnnotationCreate.model_validate({
                "revision_id": revision_id,
                "kind": kind,
                "segments": segments,
                "scope": scope,
                "project_id": project_id,
                "color": color,
                "body": body,
                "selected_text": selected_text,
            })
            return AnnotationView.model_validate(
                create_document_annotation(db, user, item_id, data)
            )

        return runtime.call(
            "annotations.create",
            run,
            conceal_resource="document not found",
        )

    @server.tool(
        name="annotations.update",
        description="Update an editable annotation using optimistic version checking.",
        annotations=WRITE,
    )
    def annotations_update(
        item_id: str,
        annotation_id: str,
        version: int,
        scope: Literal["private", "project"] | None = None,
        project_id: str | None = None,
        color: Literal["yellow", "green", "blue", "red"] | None = None,
        body: str | None = None,
    ) -> AnnotationView:
        def run(db, user):
            data = AnnotationUpdate.model_validate({
                "version": version,
                "scope": scope,
                "project_id": project_id,
                "color": color,
                "body": body,
            })
            return AnnotationView.model_validate(
                update_document_annotation(db, user, item_id, annotation_id, data)
            )

        return runtime.call(
            "annotations.update",
            run,
            conceal_resource="annotation not found",
        )

    @server.tool(
        name="annotations.delete",
        description="Soft-delete an annotation editable by the authenticated User.",
        annotations=DESTRUCTIVE,
    )
    def annotations_delete(item_id: str, annotation_id: str) -> dict[str, bool]:
        runtime.call(
            "annotations.delete",
            lambda db, user: delete_document_annotation(db, user, item_id, annotation_id),
            conceal_resource="annotation not found",
        )
        return {"ok": True}
