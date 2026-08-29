from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.accounts.authentication import (
    InvalidCredentials,
    authenticate_user,
)
from quirebase.accounts.authentication import (
    accept_invitation as accept_invitation_op,
)
from quirebase.accounts.authentication import (
    change_own_password as change_own_password_op,
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
from quirebase.core.errors import ValidationFailure
from quirebase.core.i18n import normalize_locale
from quirebase.models import LoginSession, User
from quirebase.operations.settings import get_effective_setting
from quirebase.web.deps import (
    current_login,
    current_user,
    login_identity,
    protected_router,
)
from quirebase.web.deps import (
    public_router as make_public_router,
)
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

public_router = make_public_router()
router = protected_router()


@public_router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@public_router.post("/login")
def login(
    request: Request,
    username: str = Form(),
    password: str = Form(),
    db: Session = Depends(get_db),
):
    identity = login_identity(request, username)
    session_days = get_effective_setting(db, "session_days", get_settings().session_days)
    try:
        _session, raw_token = authenticate_user(
            db, identity, username, password, session_days=session_days
        )
    except InvalidCredentials:
        return templates.TemplateResponse(
            request, "login.html", {"error": "Invalid credentials"}, status_code=401
        )

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        get_settings().session_cookie,
        raw_token,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        max_age=session_days * 86400,
    )
    return response


@public_router.get("/accept-invitation/{token}", response_class=HTMLResponse)
def accept_invitation_page(request: Request, token: str, db: Session = Depends(get_db)):
    invitation = get_valid_invitation(db, token)
    return templates.TemplateResponse(
        request,
        "accept_invitation.html",
        {"token": token, "invitation": invitation},
    )


@public_router.post("/accept-invitation/{token}")
def accept_invitation(token: str, password: str = Form(), db: Session = Depends(get_db)):
    accept_invitation_op(db, token, password)
    return RedirectResponse("/login", status_code=303)


@router.get("/account/settings", response_class=HTMLResponse)
def account_settings_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    sessions = list_user_sessions(db, user.id)
    return templates.TemplateResponse(
        request,
        "account_settings.html",
        {
            "user": user,
            "login": login_session,
            "sessions": sessions,
            "csrf": login_session.csrf_token,
            "active_page": "settings",
            "error": None,
            "success": None,
        },
    )


@router.post("/account/settings/locale")
def update_locale(
    locale: str = Form(),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
):
    norm = normalize_locale(locale)
    response = RedirectResponse("/account/settings", status_code=303)
    response.set_cookie(
        "quirebase_locale",
        norm,
        max_age=365 * 86400,
        httponly=False,
        samesite="lax",
    )
    return response


@router.post("/account/settings/password")
def update_password(
    request: Request,
    current_password: str = Form(),
    new_password: str = Form(),
    confirm_password: str = Form(),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    sessions = list_user_sessions(db, user.id)
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "account_settings.html",
            {
                "user": user,
                "login": login_session,
                "sessions": sessions,
                "csrf": login_session.csrf_token,
                "active_page": "settings",
                "error": "New passwords do not match",
                "success": None,
            },
            status_code=422,
        )
    try:
        change_own_password_op(db, user, current_password, new_password)
    except (InvalidCredentials, ValidationFailure) as err:
        return templates.TemplateResponse(
            request,
            "account_settings.html",
            {
                "user": user,
                "login": login_session,
                "sessions": sessions,
                "csrf": login_session.csrf_token,
                "active_page": "settings",
                "error": str(err),
                "success": None,
            },
            status_code=422,
        )
    return templates.TemplateResponse(
        request,
        "account_settings.html",
        {
            "user": user,
            "login": login_session,
            "sessions": sessions,
            "csrf": login_session.csrf_token,
            "active_page": "settings",
            "error": None,
            "success": "Password updated successfully",
        },
    )


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
            "active_page": "settings",
        },
    )


@router.post("/account/sessions/{session_id}/revoke")
def revoke_session(
    request: Request,
    session_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_session_op(db, user, session_id)
    referer = request.headers.get("referer")
    target = "/account/settings" if referer and "settings" in referer else "/account/sessions"
    return RedirectResponse(target, status_code=303)


@router.post("/account/sessions/revoke-all")
def revoke_all_sessions(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_all_sessions_op(db, user)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie)
    return response


@router.post("/logout")
def logout(
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    logout_op(db, user, login_session)
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(get_settings().session_cookie)
    return response
