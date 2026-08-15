from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from quirebase.core.database import get_db
from quirebase.models import User
from quirebase.operations import check_health, get_system_metrics
from quirebase.web.deps import current_user

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/healthz")
def healthz():
    return check_health()


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_system_metrics(db, user)
