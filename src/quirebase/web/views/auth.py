from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.accounts.authentication import (
    InvalidCredentials,
    authenticate_user,
)
from quirebase.accounts.authentication import (
    accept_invitation as accept_invitation_op,
)
from quirebase.accounts.authentication import (
    logout as logout_op,
)
from quirebase.accounts.invitations import get_valid_invitation
from quirebase.accounts.sessions import (
    list_user_sessions,
)
from quirebase.accounts.sessions import (
    revoke_all_sessions as revoke_all_sessions_op,
)
from quirebase.accounts.sessions import (
    revoke_session as revoke_session_op,
)
from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.models import LoginSession, User
from quirebase.web.deps import current_login, current_user, login_identity, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.post("/login")
def login(
    request: Request,
    username: str = Form(),
    password: str = Form(),
    db: Session = Depends(get_db),
):
    identity = login_identity(request, username)
    try:
        _login_session, raw = authenticate_user(
            db, identity, username, password, session_days=get_settings().session_days
        )
    except InvalidCredentials:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials"}, status_code=401
        )
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        get_settings().session_cookie,
        raw,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        max_age=get_settings().session_days * 86400,
    )
    return response


@router.get("/accept-invitation/{token}", response_class=HTMLResponse)
def accept_invitation_page(request: Request, token: str, db: Session = Depends(get_db)):
    invitation = get_valid_invitation(db, token)
    return templates.TemplateResponse(
        request,
        "accept_invitation.html",
        {"token": token, "invitation": invitation},
    )


@router.post("/accept-invitation/{token}")
def accept_invitation(token: str, password: str = Form(), db: Session = Depends(get_db)):
    accept_invitation_op(db, token, password)
    return RedirectResponse("/login", status_code=303)


@router.get("/account/sessions", response_class=HTMLResponse)
def sessions_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    sessions = list_user_sessions(db, user.id)
    return templates.TemplateResponse(
        request,
        "sessions.html",
        {
            "user": user,
            "login": login_session,
            "sessions": sessions,
            "csrf": login_session.csrf_token,
            "active_page": "sessions",
        },
    )


@router.post("/account/sessions/{session_id}/revoke", dependencies=[Depends(require_csrf)])
def revoke_session(
    session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    revoke_session_op(db, user, session_id)
    return RedirectResponse("/account/sessions", status_code=303)


@router.post("/account/sessions/revoke-all", dependencies=[Depends(require_csrf)])
def revoke_all_sessions(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_all_sessions_op(db, user)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie)
    return response


@router.post("/logout", dependencies=[Depends(require_csrf)])
def logout(
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    logout_op(db, user, login_session)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie)
    return response
