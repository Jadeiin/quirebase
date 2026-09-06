from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.core.database import get_db
from quirebase.models import LoginSession, ProjectState, User
from quirebase.projects import (
    add_project_member as add_project_member_op,
)
from quirebase.projects import (
    create_project as create_project_op,
)
from quirebase.projects import (
    delete_project,
    join_project,
    leave_project,
    list_joinable_projects,
    list_user_projects,
    open_project_workspace,
    rename_project,
    set_project_state,
    set_project_visibility,
    transfer_project_ownership,
    update_project_description,
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
    visibility: str = Form(default="private"),
    description: str = Form(default=""),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await create_project_op(db, user, name, visibility, description)
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


@router.get("/projects", response_class=HTMLResponse)
async def projects_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    projects = await list_user_projects(db, user)
    joinable_projects = await list_joinable_projects(db, user)
    return templates.TemplateResponse(
        request,
        "projects.html",
        {
            "user": user,
            "projects": projects,
            "joinable_projects": joinable_projects,
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


@router.post("/projects/{project_id}/rename")
async def rename_project_page(
    project_id: str,
    name: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await rename_project(db, user, project_id, name)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/description")
async def update_project_description_page(
    project_id: str,
    description: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await update_project_description(db, user, project_id, description)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/delete")
async def delete_project_page(
    project_id: str,
    confirmation: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_project(db, user, project_id, confirmation)
    return RedirectResponse("/projects", status_code=303)


@router.post("/projects/{project_id}/archive")
async def archive_project_page(
    project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await set_project_state(db, user, project_id, ProjectState.archived)
    return RedirectResponse("/projects", status_code=303)


@router.post("/projects/{project_id}/restore")
async def restore_project_page(
    project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await set_project_state(db, user, project_id, ProjectState.active)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/visibility")
async def set_visibility_page(
    project_id: str,
    visibility: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await set_project_visibility(db, user, project_id, visibility)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/leave")
async def leave_project_page(
    project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await leave_project(db, user, project_id)
    return RedirectResponse("/projects", status_code=303)


@router.post("/projects/{project_id}/join")
async def join_project_page(
    project_id: str, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    await join_project(db, user, project_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/ownership")
async def transfer_project_page(
    project_id: str,
    target_user_id: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await transfer_project_ownership(db, user, project_id, target_user_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/ownership/{user_id}")
async def transfer_project_page_legacy(
    project_id: str,
    user_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await transfer_project_ownership(db, user, project_id, user_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
