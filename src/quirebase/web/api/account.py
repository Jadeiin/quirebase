from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from quirebase.accounts import (
    accept_invitation,
    change_own_password,
    create_api_token,
    get_login_session_by_token,
    get_valid_invitation,
    list_api_tokens,
    list_user_sessions,
    revoke_all_sessions,
    revoke_api_token,
    revoke_session,
)
from quirebase.core.config import get_settings
from quirebase.web.api.account_schemas import (
    AccountSummaryView,
    ApiTokenCreateRequest,
    ApiTokenGrantView,
    ApiTokenView,
    InvitationAcceptRequest,
    InvitationDetailsView,
    LocaleRequest,
    PasswordChangeRequest,
)
from quirebase.web.api.auth import require_same_origin
from quirebase.web.api.common import OkView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.session_schemas import LoginSessionView
from quirebase.web.errors import ApiHTTPException
from quirebase.web.locale import normalize_locale

router = APIRouter(tags=["HTTP API"])


@router.get("/invitations/{token}", response_model=InvitationDetailsView)
async def invitation_details(token: str, db: Database):
    invitation = await get_valid_invitation(db, token)
    if invitation is None:
        raise ApiHTTPException(
            status.HTTP_404_NOT_FOUND,
            "invitation_not_found",
            "invitation not found or expired",
        )
    return {
        "username": invitation.username,
        "role": invitation.role,
        "expires_at": invitation.expires_at,
    }


@router.post("/invitations/{token}/accept", response_model=OkView)
async def accept_user_invitation(
    token: str, data: InvitationAcceptRequest, request: Request, db: Database
) -> OkView:
    require_same_origin(request)
    await accept_invitation(db, token, data.password)
    return OkView()


@router.get("/account", response_model=AccountSummaryView)
async def account_summary(request: Request, user: ApiUser, db: Database):

    raw_session = request.cookies.get(get_settings().session_cookie, "")
    current = await get_login_session_by_token(db, raw_session)
    sessions = await list_user_sessions(db, user.id)
    tokens = await list_api_tokens(db, user)
    return {
        "user": {"id": user.id, "username": user.username, "role": user.role},
        "sessions": [
            LoginSessionView(
                id=session.id,
                current=current is not None and session.id == current.id,
                expires_at=session.expires_at,
                created_at=session.created_at,
            )
            for session in sessions
        ],
        "api_tokens": [
            ApiTokenView(
                id=token.token_id,
                name=token.name,
                status=token.status,
                expires_at=token.expires_at,
                created_at=token.created_at,
            )
            for token in tokens
        ],
    }


@router.post(
    "/account/api-tokens",
    response_model=ApiTokenGrantView,
    status_code=status.HTTP_201_CREATED,
)
async def create_own_api_token(
    data: ApiTokenCreateRequest, user: ApiUser, db: Database, response: Response
) -> ApiTokenGrantView:
    grant = await create_api_token(db, user, data.name, expires_in_days=data.days)
    response.headers["Cache-Control"] = "no-store"
    return ApiTokenGrantView(id=grant.token_id, token=grant.raw_token, expires_at=grant.expires_at)


@router.delete("/account/api-tokens/{token_id}", response_model=OkView)
async def revoke_own_api_token(token_id: str, user: ApiUser, db: Database) -> OkView:
    await revoke_api_token(db, user, token_id)
    return OkView()


@router.put("/account/locale", response_model=OkView)
async def update_locale(data: LocaleRequest, user: ApiUser, response: Response) -> OkView:
    del user
    response.set_cookie(
        "quirebase_locale",
        normalize_locale(data.locale),
        max_age=365 * 86400,
        httponly=False,
        secure=get_settings().secure_cookies,
        samesite="lax",
    )
    return OkView()


@router.put("/account/password", response_model=OkView)
async def update_password(data: PasswordChangeRequest, user: ApiUser, db: Database) -> OkView:
    await change_own_password(db, user, data.current_password, data.new_password)
    return OkView()


@router.delete("/account/sessions/{session_id}", response_model=OkView)
async def revoke_own_session(session_id: str, user: ApiUser, db: Database) -> OkView:
    await revoke_session(db, user, session_id)
    return OkView()


@router.delete("/account/sessions", response_model=OkView)
async def revoke_all_own_sessions(user: ApiUser, db: Database, response: Response) -> OkView:
    await revoke_all_sessions(db, user)
    response.delete_cookie(get_settings().session_cookie)
    return OkView()
