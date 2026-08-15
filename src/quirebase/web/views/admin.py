from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.accounts.administration import (
    list_failed_jobs,
    list_invitations,
    list_users,
)
from quirebase.accounts.administration import (
    retry_job as retry_job_op,
)
from quirebase.accounts.invitations import create_invitation as create_invitation_op
from quirebase.core.database import get_db
from quirebase.models import LoginSession, User
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    users = list_users(db, user)
    invitations = list_invitations(db, user)
    failed_jobs = list_failed_jobs(db, user)
    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "users": users,
            "invitations": invitations,
            "failed_jobs": failed_jobs,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post(
    "/admin/invitations", dependencies=[Depends(require_csrf)], response_class=HTMLResponse
)
def create_invitation(
    request: Request,
    username: str = Form(),
    role: str = Form(default="member"),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    invitation, raw = create_invitation_op(db, user, username, role)
    return templates.TemplateResponse(
        request,
        "invitation_created.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "invitation": invitation,
            "invite_url": str(request.url_for("accept_invitation_page", token=raw)),
            "active_page": "admin",
        },
    )


@router.post("/admin/jobs/{job_id}/retry", dependencies=[Depends(require_csrf)])
def retry_job(
    job_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    retry_job_op(db, user, job_id)
    return RedirectResponse("/admin", status_code=303)
