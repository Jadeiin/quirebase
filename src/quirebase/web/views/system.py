from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends
from fastapi.responses import PlainTextResponse

from quirebase.core.database import get_db
from quirebase.models import User
from quirebase.operations import check_health, get_system_metrics
from quirebase.web.deps import (
    current_user,
    protected_router,
)
from quirebase.web.deps import (
    public_router as make_public_router,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

public_router = make_public_router()
router = protected_router()


@public_router.get("/healthz")
def healthz():
    return check_health()


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return get_system_metrics(db, user)
