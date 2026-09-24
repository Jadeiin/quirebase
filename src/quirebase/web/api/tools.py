from fastapi import APIRouter, status

from quirebase.library import (
    create_custom_citation_style,
    delete_custom_citation_style,
    delete_tag,
    find_duplicates,
    list_custom_citation_styles,
    merge_tags,
    preview_citation_key,
    rename_tag,
    select_builtin_citation_styles,
)
from quirebase.web.api.common import OkView, WriteResult
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.export_schemas import CitationKeyPreviewView
from quirebase.web.api.library_schemas import (
    CitationStylesResponseView,
    NameRequest,
    item_search_view,
)
from quirebase.web.api.tool_schemas import (
    CitationStyleCreateRequest,
    DuplicatesReviewView,
    TagMergeRequest,
)

router = APIRouter(tags=["Library tools"])


@router.get("/citation-key-preview", response_model=CitationKeyPreviewView)
async def citation_key_preview(
    formula: str,
    _user: ApiUser,
    force_ascii: bool = False,
):
    return {"key": preview_citation_key(formula, force_ascii=force_ascii)}


@router.get("/citation-styles", response_model=CitationStylesResponseView)
async def citation_styles(
    workspace_id: str,
    user: ApiUser,
    db: Database,
    query: str = "",
    limit: int = 50,
    include: str = "",
):
    normalized = query.strip().casefold()
    builtin_selection = select_builtin_citation_styles(query, limit=limit, include=include)
    owned_custom_styles = await list_custom_citation_styles(db, user, workspace_id)
    custom = [
        {"key": style.id, "name": style.name, "scope": "custom"}
        for style in owned_custom_styles
        if style.id != include and (not normalized or normalized in style.name.casefold())
    ]
    exact_custom = next(
        (
            {"key": style.id, "name": style.name, "scope": "custom"}
            for style in owned_custom_styles
            if include and style.id == include
        ),
        None,
    )
    included = []
    if builtin_selection.included is not None:
        included.append({
            "key": builtin_selection.included.key,
            "name": builtin_selection.included.name,
            "scope": "builtin",
        })
    if exact_custom is not None:
        included.append(exact_custom)
    styles = [
        {"key": style.key, "name": style.name, "scope": "builtin"}
        for style in builtin_selection.matches
    ][:limit] + custom[:limit]
    included = [
        style for style in included if not any(style["key"] == item["key"] for item in styles)
    ]
    return {"styles": styles + included}


@router.get("/duplicates", response_model=DuplicatesReviewView)
async def duplicate_items(workspace_id: str, user: ApiUser, db: Database, mode: str = ""):
    return {
        "groups": [
            [item_search_view(item) for item in group]
            for group in await find_duplicates(db, user, workspace_id, mode)
        ]
    }


@router.post("/citation-styles", status_code=status.HTTP_201_CREATED)
async def create_citation_style(
    workspace_id: str, data: CitationStyleCreateRequest, user: ApiUser, db: Database
) -> WriteResult:
    style = await create_custom_citation_style(db, user, workspace_id, data.name, data.csl)
    return WriteResult(id=style.id)


@router.delete("/citation-styles/{style_id}")
async def delete_citation_style(
    workspace_id: str, style_id: str, user: ApiUser, db: Database
) -> OkView:
    await delete_custom_citation_style(db, user, workspace_id, style_id)
    return OkView()


@router.post("/tags/merge")
async def merge_user_tags(
    workspace_id: str, data: TagMergeRequest, user: ApiUser, db: Database
) -> OkView:
    await merge_tags(db, user, workspace_id, data.source_tag_id, data.target_tag_id)
    return OkView()


@router.patch("/tags/{tag_id}")
async def rename_user_tag(
    workspace_id: str, tag_id: str, data: NameRequest, user: ApiUser, db: Database
) -> OkView:
    await rename_tag(db, user, workspace_id, tag_id, data.name)
    return OkView()


@router.delete("/tags/{tag_id}")
async def delete_user_tag(workspace_id: str, tag_id: str, user: ApiUser, db: Database) -> OkView:
    await delete_tag(db, user, workspace_id, tag_id)
    return OkView()
