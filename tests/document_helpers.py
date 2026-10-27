from __future__ import annotations

from uuid import uuid4

from advanced_alchemy.types import FileObject
from workspace_helpers import fixture_workspace_id, workspace_user

from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    FileRevision,
    Item,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    WorkspaceMember,
    WorkspaceRole,
)


async def shared_annotation_context(db, name: str):
    author = await workspace_user(db, f"{name}-author")
    viewer = await workspace_user(db, f"{name}-viewer")
    workspace_id = fixture_workspace_id(author)
    db.add(
        WorkspaceMember(
            workspace_id=workspace_id,
            user_id=viewer.id,
            role=WorkspaceRole.viewer,
            invited_by=author.id,
        )
    )
    item = Item(
        workspace_id=workspace_id,
        created_by=author.id,
        work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": name},
    )
    project = Project(workspace_id=workspace_id, name=name, created_by=author.id)
    db.add_all([item, project])
    await db.flush()
    project_item = ProjectItem(
        workspace_id=workspace_id, project_id=project.id, item_id=item.id, added_by=author.id
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        created_by=author.id,
        file=FileObject(
            backend="documents",
            filename=f"objects/{name}.pdf",
            size=1,
            content_type="application/pdf",
            metadata={"original_name": f"{name}.pdf"},
        ),
    )
    db.add_all([project_item, revision])
    await db.flush()
    annotation = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=project_item.id,
        body="Shared note",
        payload={"type": "note", "rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
    )
    db.add(annotation)
    await db.flush()
    reply = PdfAnnotationReply(
        workspace_id=workspace_id,
        annotation_id=annotation.id,
        author_id=author.id,
        body="Shared reply",
    )
    db.add(reply)
    await db.commit()
    return (author, viewer, item, project, revision, annotation, reply)
