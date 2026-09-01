from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Form, Request
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
    list_user_projects,
    open_project_workspace,
)
from quirebase.projects import (
    remove_project_member as remove_project_member_op,
)
from quirebase.web.deps import current_login, current_user, protected_router
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = protected_router()


@router.post("/projects")
async def create_project(
    name: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await create_project_op(db, user, name)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    projects = await list_user_projects(db, user)
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
async def project_page(
    request: Request,
    project_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    workspace = await open_project_workspace(db, user, project_id)
    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "active_page": "projects",
            "project": workspace.project,
            "membership": workspace.membership,
            "members": tuple((member.user, member.role) for member in workspace.members),
            "items": workspace.items,
        },
    )


@router.post("/projects/{project_id}/members")
async def add_project_member(
    project_id: str,
    username: str = Form(),
    role: str = Form(default="viewer"),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await add_project_member_op(db, user, project_id, username, role)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/members/{member_id}/remove")
async def remove_project_member(
    project_id: str,
    member_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await remove_project_member_op(db, user, project_id, member_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
