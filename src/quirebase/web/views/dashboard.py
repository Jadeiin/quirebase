from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from quirebase.core.database import get_db
from quirebase.library import get_dashboard_data
from quirebase.models import LoginSession, User
from quirebase.web.deps import current_login, current_user, protected_router
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = protected_router()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    q: str = "",
    user: User = Depends(current_user),
    login: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    if q.strip():
        return RedirectResponse(f"/library?{urlencode({'q': q.strip()})}", status_code=303)
    data = get_dashboard_data(db, user)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "user": user,
            "new_items": data["new_items"],
            "recent_items": data["recent_items"],
            "projects": data["projects"],
            "sessions": data["sessions"],
            "current_login": login,
            "csrf": login.csrf_token,
            "active_page": "dashboard",
        },
    )
