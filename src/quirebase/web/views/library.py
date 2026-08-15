from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

from quirebase.access import editable_projects, visible_projects
from quirebase.citation import available_builtin_styles
from quirebase.core.database import get_db
from quirebase.discovery import export_selected_bibliography
from quirebase.library import bulk_action, bulk_download_pdfs, search_library
from quirebase.models import LoginSession, User
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/library", response_class=HTMLResponse)
def library(
    request: Request,
    q: str = "",
    tag: str = "",
    project: str = "",
    year: str = "",
    keyword: str = "",
    author: str = "",
    page: int = 1,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    page = max(page, 1)
    per_page = 25
    items, total, tags, years = search_library(
        db,
        user,
        q=q,
        tag=tag,
        project=project,
        year=year,
        keyword=keyword,
        author=author,
        page=page,
        per_page=per_page,
    )
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "user": user,
            "items": items,
            "projects": visible_projects(db, user),
            "editable_projects": editable_projects(db, user),
            "tags": tags,
            "years": years,
            "csrf": login_session.csrf_token,
            "active_page": "library",
            "builtin_styles": available_builtin_styles(),
            "filters": {
                "q": q,
                "tag": tag,
                "project": project,
                "year": year,
                "keyword": keyword,
                "author": author,
            },
            "page": page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "total": total,
        },
    )


@router.post("/library/bulk", dependencies=[Depends(require_csrf)])
def library_bulk_action(
    action: str = Form(),
    item_ids: list[str] = Form(default=[]),
    project_id: str = Form(default=""),
    tag_name: str = Form(default=""),
    confirm_delete: str = Form(default=""),
    style: str = Form(default="apa"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if action == "export_csl":
        contents, media_type, filename = export_selected_bibliography(
            db, user, item_ids, "csl", style_key=style
        )
        return Response(
            contents,
            media_type=f"{media_type}; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if action.startswith("export_"):
        contents, media_type, filename = export_selected_bibliography(
            db, user, item_ids, action.removeprefix("export_")
        )
        return Response(
            contents,
            media_type=f"{media_type}; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    if action == "download_pdfs":
        archive = bulk_download_pdfs(db, user, item_ids)
        return StreamingResponse(
            archive,
            media_type="application/zip",
            headers={"Content-Disposition": 'attachment; filename="quirebase-pdfs.zip"'},
        )

    bulk_action(
        db,
        user,
        item_ids=item_ids,
        action=action,
        project_id=project_id,
        tag_name=tag_name,
        confirm_delete=confirm_delete,
    )
    return RedirectResponse("/library", status_code=303)
