from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.core.database import get_db
from quirebase.discovery import (
    available_builtin_styles,
    create_custom_citation_style,
    delete_custom_citation_style,
    list_custom_citation_styles,
)
from quirebase.library import (
    delete_tag as delete_tag_op,
)
from quirebase.library import (
    find_duplicates,
    list_accessible_tags_with_counts,
)
from quirebase.library import (
    rename_tag as rename_tag_op,
)
from quirebase.models import LoginSession, User
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/tools", response_class=HTMLResponse)
def tools_page(
    request: Request,
    tab: str = "",
    mode: str = "",
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    if mode not in ("", "doi", "pdf", "title", "similar"):
        raise HTTPException(404)
    if tab not in ("", "duplicates", "tags", "citation-styles"):
        tab = "duplicates"
    active_tool = tab or "duplicates"
    groups = find_duplicates(db, user, mode)
    tags = list_accessible_tags_with_counts(db, user)
    tags_data = [{"id": tag.id, "name": tag.name, "count": count} for tag, count in tags]
    custom_styles = list_custom_citation_styles(db, user)
    return templates.TemplateResponse(
        request,
        "tools.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "tab": tab,
            "mode": mode,
            "active_tool": active_tool,
            "groups": groups,
            "tags": tags,
            "tags_data": tags_data,
            "custom_styles": custom_styles,
            "builtin_styles": available_builtin_styles(),
            "active_page": "tools",
        },
    )


@router.post("/citation-styles", dependencies=[Depends(require_csrf)])
def create_citation_style(
    name: str = Form(),
    csl: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    create_custom_citation_style(db, user, name, csl)
    return RedirectResponse("/tools?tab=citation-styles#citation-styles", status_code=303)


@router.post("/citation-styles/{style_id}/delete", dependencies=[Depends(require_csrf)])
def delete_citation_style(
    style_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    delete_custom_citation_style(db, user, style_id)
    return RedirectResponse("/tools?tab=citation-styles#citation-styles", status_code=303)


@router.post("/tools/tags/{tag_id}", dependencies=[Depends(require_csrf)])
def rename_tag(
    tag_id: str,
    name: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rename_tag_op(db, user, tag_id, name)
    return RedirectResponse("/tools?tab=tags#tags", status_code=303)


@router.post("/tools/tags/{tag_id}/delete", dependencies=[Depends(require_csrf)])
def delete_tag(
    tag_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    delete_tag_op(db, user, tag_id)
    return RedirectResponse("/tools?tab=tags#tags", status_code=303)
