from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from quirebase.accounts import get_login_session_by_token
from quirebase.accounts.authentication import InvalidCredentials, authenticate_user
from quirebase.accounts.authentication import logout as logout_op
from quirebase.core.config import get_settings
from quirebase.core.crypto import token_hash
from quirebase.models import User
from quirebase.operations.settings import get_effective_setting
from quirebase.web.api.auth import require_same_origin
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.session_schemas import LoginRequest, SessionView
from quirebase.web.errors import ApiHTTPException

router = APIRouter(tags=["Session"])


@router.get("/session", response_model=SessionView)
async def session_bootstrap(request: Request, db: Database):
    raw_session = request.cookies.get(get_settings().session_cookie, "")
    login = await get_login_session_by_token(db, raw_session)
    if login is None:
        return {"authenticated": False, "user": None}
    return {
        "authenticated": True,
        "user": {"id": login.user.id, "username": login.user.username, "role": login.user.role},
    }


@router.post("/session", response_model=SessionView)
async def login_session(
    request: Request,
    response: Response,
    data: LoginRequest,
    db: Database,
):
    require_same_origin(request)
    address = request.client.host if request.client else "unknown"
    identity = token_hash(f"{address}\0{data.username.casefold()}")
    session_days = await get_effective_setting(db, "session_days", get_settings().session_days)
    try:
        login, raw_token = await authenticate_user(
            db,
            identity,
            data.username,
            data.password,
            session_days=session_days,
        )
    except InvalidCredentials as error:
        raise ApiHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="invalid_credentials",
            message="invalid credentials",
        ) from error
    response.set_cookie(
        get_settings().session_cookie,
        raw_token,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="lax",
        max_age=session_days * 86400,
    )
    response.headers["Cache-Control"] = "no-store"
    user = await db.get(User, login.user_id)
    if user is None:  # pragma: no cover - the Login Session foreign key guarantees this
        raise ApiHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="authentication_required",
            message="authentication required",
        )
    return {
        "authenticated": True,
        "user": {"id": user.id, "username": user.username, "role": user.role},
    }


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout_session(request: Request, response: Response, user: ApiUser, db: Database) -> None:
    raw_session = request.cookies.get(get_settings().session_cookie, "")
    login = await get_login_session_by_token(db, raw_session)
    if login is None or login.user_id != user.id:
        raise ApiHTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="authentication_required",
            message="authentication required",
        )
    await logout_op(db, user, login)
    response.delete_cookie(get_settings().session_cookie)
