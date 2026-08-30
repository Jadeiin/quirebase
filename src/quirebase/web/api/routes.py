from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from quirebase.core.config import Settings, get_settings
from quirebase.core.database import get_db
from quirebase.documents import (
    AnnotationCreate,
    AnnotationUpdate,
    create_document_annotation,
    delete_document_annotation,
    list_document_annotations,
    update_document_annotation,
)
from quirebase.library import (
    CandidatePageView,
    DiscussionWorkspace,
    FilesWorkspace,
    ItemMetadata,
    MetadataWorkspace,
    WorkspaceSection,
    add_discussion_message,
    add_tag_to_item,
    create_item,
    delete_discussion_message,
    get_item_citation_text_response,
    list_accessible_tags_with_counts,
    open_item_workspace,
    remove_tag_from_item,
    revise_item_metadata,
    search_candidate_records,
    search_library,
    set_item_tags,
)
from quirebase.models import User
from quirebase.programmatic import (
    AnnotationView,
    CitationView,
    DiscussionMessageView,
    DocumentListView,
    ItemDetailView,
    LibrarySearchView,
    OkView,
    ProjectDetailView,
    ProjectMemberView,
    ProjectSummaryView,
    TagView,
    WriteResult,
    discussion_message_views,
    document_list_view,
    item_detail_view,
    item_search_view,
    project_detail_view,
)
from quirebase.projects import (
    add_item_to_project,
    add_project_member,
    create_project,
    list_user_projects,
    open_project_workspace,
    remove_item_from_project,
    remove_project_member,
)
from quirebase.web.api.auth import current_api_user, http_api_invocation
from quirebase.web.api.schemas import (
    DiscoverySearchRequest,
    DiscussionRequest,
    ItemUpdateRequest,
    NameRequest,
    ProjectMemberRequest,
    TagSetRequest,
)

router = APIRouter(
    prefix="/api/v1",
    tags=["HTTP API"],
    dependencies=[Depends(http_api_invocation)],
)
ApiUser = Annotated[User, Depends(current_api_user)]
Database = Annotated[Session, Depends(get_db)]


@router.get("/items", response_model=LibrarySearchView)
def search_items(
    user: ApiUser,
    db: Database,
    query: str = "",
    tag: str = "",
    project: str = "",
    year: str = "",
    keyword: str = "",
    author: str = "",
    page: Annotated[int, Query(ge=1)] = 1,
) -> LibrarySearchView:
    per_page = 25
    items, total, _tags, _years = search_library(
        db,
        user,
        q=query,
        tag=tag,
        project=project,
        year=year,
        keyword=keyword,
        author=author,
        page=page,
        per_page=per_page,
    )
    return LibrarySearchView(
        items=[item_search_view(item) for item in items],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.post("/items", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
def create_library_item(metadata: ItemMetadata, user: ApiUser, db: Database) -> WriteResult:
    result = create_item(db, user, metadata)
    return WriteResult(id=result.item_id, version=result.version)


@router.get("/items/{item_id}", response_model=ItemDetailView)
def get_library_item(item_id: str, user: ApiUser, db: Database) -> ItemDetailView:
    workspace = open_item_workspace(db, user, item_id, WorkspaceSection.metadata)
    if not isinstance(workspace, MetadataWorkspace):  # pragma: no cover
        raise TypeError("item metadata workspace mismatch")
    return item_detail_view(workspace)


@router.put("/items/{item_id}", response_model=WriteResult)
def update_library_item(
    item_id: str, data: ItemUpdateRequest, user: ApiUser, db: Database
) -> WriteResult:
    result = revise_item_metadata(db, user, item_id, data.expected_version, data.metadata)
    return WriteResult(id=result.item_id, version=result.version)


@router.get("/items/{item_id}/citation", response_model=CitationView)
def format_item_citation(
    item_id: str,
    user: ApiUser,
    db: Database,
    style: str = "apa",
    output: Annotated[str, Query(pattern="^(text|html)$")] = "text",
) -> CitationView:
    content, media_type = get_item_citation_text_response(
        db, user, item_id, style_key=style, output=output
    )
    return CitationView(content=content, media_type=media_type)


@router.get("/projects", response_model=list[ProjectSummaryView])
def list_projects(user: ApiUser, db: Database) -> list[ProjectSummaryView]:
    return [
        ProjectSummaryView(id=project.id, name=project.name, role=role, item_count=count)
        for project, role, count in list_user_projects(db, user)
    ]


@router.post("/projects", response_model=WriteResult, status_code=status.HTTP_201_CREATED)
def create_user_project(data: NameRequest, user: ApiUser, db: Database) -> WriteResult:
    project = create_project(db, user, data.name)
    return WriteResult(id=project.id)


@router.get("/projects/{project_id}", response_model=ProjectDetailView)
def get_project(project_id: str, user: ApiUser, db: Database) -> ProjectDetailView:
    return project_detail_view(open_project_workspace(db, user, project_id))


@router.put("/projects/{project_id}/items/{item_id}", response_model=OkView)
def add_project_item(project_id: str, item_id: str, user: ApiUser, db: Database) -> OkView:
    add_item_to_project(db, user, project_id, item_id)
    return OkView()


@router.delete("/projects/{project_id}/items/{item_id}", response_model=OkView)
def remove_project_item(project_id: str, item_id: str, user: ApiUser, db: Database) -> OkView:
    remove_item_from_project(db, user, project_id, item_id)
    return OkView()


@router.put("/projects/{project_id}/members", response_model=ProjectMemberView)
def set_project_member(
    project_id: str, data: ProjectMemberRequest, user: ApiUser, db: Database
) -> ProjectMemberView:
    member = add_project_member(db, user, project_id, data.username, data.role)
    workspace = open_project_workspace(db, user, project_id)
    matched = next(row for row in workspace.members if row.user.id == member.user_id)
    return ProjectMemberView(
        user_id=matched.user.id,
        username=matched.user.username,
        role=matched.role,
    )


@router.delete("/projects/{project_id}/members/{user_id}", response_model=OkView)
def delete_project_member(project_id: str, user_id: str, user: ApiUser, db: Database) -> OkView:
    remove_project_member(db, user, project_id, user_id)
    return OkView()


@router.get("/items/{item_id}/documents", response_model=DocumentListView)
def list_documents(item_id: str, user: ApiUser, db: Database) -> DocumentListView:
    workspace = open_item_workspace(db, user, item_id, WorkspaceSection.files)
    if not isinstance(workspace, FilesWorkspace):  # pragma: no cover
        raise TypeError("item files workspace mismatch")
    return document_list_view(item_id, workspace)


@router.get("/items/{item_id}/annotations", response_model=list[AnnotationView])
def list_annotations(
    item_id: str,
    revision_id: str,
    user: ApiUser,
    db: Database,
    project_id: str | None = None,
) -> list[AnnotationView]:
    return [
        AnnotationView.model_validate(row)
        for row in list_document_annotations(db, user, item_id, revision_id, project_id)
    ]


@router.post(
    "/items/{item_id}/annotations",
    response_model=AnnotationView,
    status_code=status.HTTP_201_CREATED,
)
def create_annotation(
    item_id: str, data: AnnotationCreate, user: ApiUser, db: Database
) -> AnnotationView:
    return AnnotationView.model_validate(create_document_annotation(db, user, item_id, data))


@router.patch("/items/{item_id}/annotations/{annotation_id}", response_model=AnnotationView)
def update_annotation(
    item_id: str,
    annotation_id: str,
    data: AnnotationUpdate,
    user: ApiUser,
    db: Database,
) -> AnnotationView:
    return AnnotationView.model_validate(
        update_document_annotation(db, user, item_id, annotation_id, data)
    )


@router.delete("/items/{item_id}/annotations/{annotation_id}", response_model=OkView)
def delete_annotation(item_id: str, annotation_id: str, user: ApiUser, db: Database) -> OkView:
    delete_document_annotation(db, user, item_id, annotation_id)
    return OkView()


@router.get("/tags", response_model=list[TagView])
def list_tags(user: ApiUser, db: Database) -> list[TagView]:
    return [
        TagView(id=tag.id, name=tag.name, accessible_item_count=count)
        for tag, count in list_accessible_tags_with_counts(db, user)
    ]


@router.post("/items/{item_id}/tags", response_model=WriteResult)
def add_item_tag(item_id: str, data: NameRequest, user: ApiUser, db: Database) -> WriteResult:
    assignment = add_tag_to_item(db, user, item_id, data.name)
    return WriteResult(id=assignment.tag_id)


@router.delete("/items/{item_id}/tags/{tag_id}", response_model=OkView)
def remove_item_tag(item_id: str, tag_id: str, user: ApiUser, db: Database) -> OkView:
    remove_tag_from_item(db, user, item_id, tag_id)
    return OkView()


@router.put("/items/{item_id}/tags", response_model=OkView)
def set_item_tag_selection(
    item_id: str, data: TagSetRequest, user: ApiUser, db: Database
) -> OkView:
    set_item_tags(db, user, item_id, data.tag_ids, data.new_names)
    return OkView()


@router.get("/items/{item_id}/discussions", response_model=list[DiscussionMessageView])
def list_discussions(item_id: str, user: ApiUser, db: Database) -> list[DiscussionMessageView]:
    workspace = open_item_workspace(db, user, item_id, WorkspaceSection.discussion)
    if not isinstance(workspace, DiscussionWorkspace):  # pragma: no cover
        raise TypeError("item discussion workspace mismatch")
    return discussion_message_views(workspace)


@router.post(
    "/items/{item_id}/discussions",
    response_model=WriteResult,
    status_code=status.HTTP_201_CREATED,
)
def create_discussion(
    item_id: str, data: DiscussionRequest, user: ApiUser, db: Database
) -> WriteResult:
    message = add_discussion_message(db, user, item_id, data.body)
    return WriteResult(id=message.id)


@router.delete("/items/{item_id}/discussions/{message_id}", response_model=OkView)
def delete_discussion(item_id: str, message_id: str, user: ApiUser, db: Database) -> OkView:
    delete_discussion_message(db, user, item_id, message_id)
    return OkView()


@router.post("/discovery/search", response_model=CandidatePageView)
def search_discovery(
    data: DiscoverySearchRequest,
    user: ApiUser,
    db: Database,
    settings: Annotated[Settings, Depends(get_settings)],
) -> CandidatePageView:
    return search_candidate_records(
        db,
        user,
        data.provider,
        tuple(data.clauses),
        page=data.page,
        per_page=data.per_page,
        sort=data.sort,
        year_from=data.year_from,
        year_to=data.year_to,
        settings=settings,
    )
