from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from quirebase.core.database import get_db
from quirebase.models import User
from quirebase.operations import check_health, get_system_metrics
from quirebase.web.api.auth import current_api_user

router = APIRouter()
ApiUser = Annotated[User, Depends(current_api_user)]
Database = Annotated[AsyncSession, Depends(get_db)]


@router.get("/healthz")
async def healthz():
    return check_health()


@router.get("/metrics", response_class=PlainTextResponse)
async def metrics(user: ApiUser, db: Database):
    return await get_system_metrics(db, user)
