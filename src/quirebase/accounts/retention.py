"""Bounded retirement of credentials and completed account invitations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import and_, delete, func, or_

from quirebase.accounts.throttling import THROTTLE_WINDOW
from quirebase.core.persistence import delete_page
from quirebase.models import ApiToken, Invitation, LoginSession, LoginThrottle

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


async def purge_expired_account_records(
    db: AsyncSession,
    *,
    now: datetime,
    terminal_before: datetime,
    limit: int = 500,
) -> dict[str, int]:
    """Retire at most ``limit`` rows per table inside the caller's transaction.

    Terminal receipts retain their original completion time: reading, retrying or
    repeating revocation never extends the recovery window.
    """
    token_terminal_at = func.coalesce(ApiToken.revoked_at, ApiToken.expires_at)
    invitation_terminal_at = func.coalesce(
        Invitation.accepted_at, Invitation.revoked_at, Invitation.expires_at
    )
    tables = (
        (LoginSession, LoginSession.expires_at, LoginSession.expires_at <= now),
        (
            LoginThrottle,
            LoginThrottle.window_started_at,
            LoginThrottle.window_started_at <= now - THROTTLE_WINDOW,
        ),
        (
            ApiToken,
            token_terminal_at,
            or_(
                ApiToken.revoked_at <= terminal_before,
                and_(ApiToken.revoked_at.is_(None), ApiToken.expires_at <= terminal_before),
            ),
        ),
        (
            Invitation,
            invitation_terminal_at,
            or_(
                Invitation.accepted_at <= terminal_before,
                and_(Invitation.accepted_at.is_(None), Invitation.revoked_at <= terminal_before),
                and_(
                    Invitation.accepted_at.is_(None),
                    Invitation.revoked_at.is_(None),
                    Invitation.expires_at <= terminal_before,
                ),
            ),
        ),
    )
    counts = {}
    for model, terminal_at, condition in tables:
        counts[model.__tablename__] = await delete_page(
            db,
            delete(model).where(condition),
            order_by=(terminal_at,),
            limit=limit,
        )
    return counts
