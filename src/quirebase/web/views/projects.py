from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.core.database import get_db
from quirebase.models import LoginSession, User
from quirebase.projects import (
    add_project_member as add_project_member_op,
)
from quirebase.projects import (
    create_project as create_project_op,
)
from quirebase.projects import (
    get_project_workspace_data,
    list_user_projects,
)
from quirebase.projects import (
    remove_project_member as remove_project_member_op,
)
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.post("/projects", dependencies=[Depends(require_csrf)])
def create_project(
    name: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = create_project_op(db, user, name)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects", response_class=HTMLResponse)
def projects_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    projects = list_user_projects(db, user)
    return templates.TemplateResponse(
        request,
        "projects.html",
        {
            "user": user,
            "projects": projects,
            "csrf": login_session.csrf_token,
            "active_page": "projects",
        },
    )


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_page(
    request: Request,
    project_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    data = get_project_workspace_data(db, user, project_id)
    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "active_page": "projects",
            **data,
        },
    )


@router.post("/projects/{project_id}/members", dependencies=[Depends(require_csrf)])
def add_project_member(
    project_id: str,
    username: str = Form(),
    role: str = Form(default="viewer"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    add_project_member_op(db, user, project_id, username, role)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post(
    "/projects/{project_id}/members/{member_id}/remove", dependencies=[Depends(require_csrf)]
)
def remove_project_member(
    project_id: str,
    member_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    remove_project_member_op(db, user, project_id, member_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
