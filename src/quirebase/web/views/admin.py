from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from quirebase.accounts import (
    change_user_role,
    create_user_admin,
    list_failed_jobs,
    list_invitations,
    list_users,
    list_users_paginated,
    reset_user_password,
    revoke_user_sessions,
    update_user_status,
)
from quirebase.accounts import (
    create_invitation as create_invitation_op,
)
from quirebase.accounts import (
    retry_job as retry_job_op,
)
from quirebase.audit import query_events
from quirebase.core.database import get_db
from quirebase.library import (
    admin_delete_item,
    get_storage_metrics,
    list_global_items,
)
from quirebase.models import LoginSession, User
from quirebase.operations import (
    get_backup_artifact,
    get_runtime_settings,
    update_runtime_settings,
)
from quirebase.pipeline import (
    dispatch_maintenance_job,
    list_jobs_admin,
    retry_all_failed_jobs,
)
from quirebase.web.deps import current_login, current_user, require_admin, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter(dependencies=[Depends(require_admin)])


# =========================================================================
# 1. Overview Dashboard
# =========================================================================


@router.get("/admin", response_class=HTMLResponse)
def admin_overview_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    users = list_users(db, user)
    invitations = list_invitations(db, user)
    failed_jobs = list_failed_jobs(db, user)
    storage = get_storage_metrics(db, user)
    recent_events, _ = query_events(db, user, page=1, page_size=10)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "overview",
            "users": users,
            "invitations": invitations,
            "failed_jobs": failed_jobs,
            "storage": storage,
            "recent_events": recent_events,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


# =========================================================================
# 2. Users & Access Management
# =========================================================================


@router.get("/admin/users", response_class=HTMLResponse)
def admin_users_page(
    request: Request,
    search: str = Query(default=""),
    role: str = Query(default=""),
    active: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    active_filter = None
    if active == "true":
        active_filter = True
    elif active == "false":
        active_filter = False

    users, total_users = list_users_paginated(
        db, user, search=search, role=role, active=active_filter, page=page, page_size=20
    )
    invitations = list_invitations(db, user)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "users",
            "users": users,
            "total_users": total_users,
            "page": page,
            "search": search,
            "role": role,
            "active_filter": active,
            "invitations": invitations,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post("/admin/users/create", dependencies=[Depends(require_csrf)])
def admin_create_user(
    username: str = Form(),
    password: str = Form(),
    role: str = Form(default="member"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    create_user_admin(db, user, username, password, role)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/status", dependencies=[Depends(require_csrf)])
def admin_toggle_user_status(
    user_id: str,
    active: bool = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    update_user_status(db, user, user_id, active)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/role", dependencies=[Depends(require_csrf)])
def admin_change_user_role(
    user_id: str,
    role: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    change_user_role(db, user, user_id, role)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/password", dependencies=[Depends(require_csrf)])
def admin_reset_user_password(
    user_id: str,
    password: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    reset_user_password(db, user, user_id, password)
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/admin/users/{user_id}/revoke-sessions", dependencies=[Depends(require_csrf)])
def admin_revoke_user_sessions(
    user_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    revoke_user_sessions(db, user, user_id)
    return RedirectResponse("/admin/users", status_code=303)


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


# =========================================================================
# 3. Global Items & Storage
# =========================================================================


@router.get("/admin/items", response_class=HTMLResponse)
def admin_items_page(
    request: Request,
    search: str = Query(default=""),
    has_pdf: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    has_pdf_filter = None
    if has_pdf == "true":
        has_pdf_filter = True
    elif has_pdf == "false":
        has_pdf_filter = False

    items, total_items = list_global_items(
        db, user, search=search, has_pdf=has_pdf_filter, page=page, page_size=20
    )
    storage = get_storage_metrics(db, user)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "items",
            "items": items,
            "total_items": total_items,
            "page": page,
            "search": search,
            "has_pdf": has_pdf,
            "storage": storage,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post("/admin/items/{item_id}/delete", dependencies=[Depends(require_csrf)])
def admin_delete_item_endpoint(
    item_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    admin_delete_item(db, user, item_id)
    return RedirectResponse("/admin/items", status_code=303)


# =========================================================================
# 4. Audit Event Explorer
# =========================================================================


@router.get("/admin/audit", response_class=HTMLResponse)
def admin_audit_page(
    request: Request,
    search: str = Query(default=""),
    actor_id: str = Query(default=""),
    action: str = Query(default=""),
    target_type: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    events, total_events = query_events(
        db,
        user,
        actor_id=actor_id.strip() or None,
        action=action.strip() or None,
        target_type=target_type.strip() or None,
        search=search,
        page=page,
        page_size=50,
    )

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "audit",
            "events": events,
            "total_events": total_events,
            "page": page,
            "search": search,
            "actor_id": actor_id,
            "action_filter": action,
            "target_type": target_type,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


# =========================================================================
# 5. Background Pipeline Jobs
# =========================================================================


@router.get("/admin/jobs", response_class=HTMLResponse)
def admin_jobs_page(
    request: Request,
    state: str = Query(default=""),
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    jobs = list_jobs_admin(db, user, state=state, limit=100)
    failed_jobs = list_failed_jobs(db, user)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "jobs",
            "jobs": jobs,
            "failed_jobs": failed_jobs,
            "state_filter": state,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post("/admin/jobs/{job_id}/retry", dependencies=[Depends(require_csrf)])
def retry_job_endpoint(
    job_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    retry_job_op(db, user, job_id)
    return RedirectResponse("/admin/jobs", status_code=303)


@router.post("/admin/jobs/retry-all", dependencies=[Depends(require_csrf)])
def retry_all_jobs_endpoint(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    retry_all_failed_jobs(db, user)
    return RedirectResponse("/admin/jobs", status_code=303)


# =========================================================================
# 6. Runtime Settings
# =========================================================================


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    settings_data = get_runtime_settings(db)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "settings",
            "settings": settings_data,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post("/admin/settings", dependencies=[Depends(require_csrf)])
def admin_update_settings_endpoint(
    metadata_contact_email: str = Form(default=""),
    ncbi_api_key: str = Form(default=""),
    openalex_api_key: str = Form(default=""),
    nasa_ads_token: str = Form(default=""),
    ieee_api_key: str = Form(default=""),
    session_days: int = Form(default=30),
    max_pdf_bytes: int = Form(default=262144000),
    max_attachment_bytes: int = Form(default=262144000),
    export_ttl_hours: int = Form(default=24),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    updates = {
        "metadata_contact_email": metadata_contact_email,
        "ncbi_api_key": ncbi_api_key,
        "openalex_api_key": openalex_api_key,
        "nasa_ads_token": nasa_ads_token,
        "ieee_api_key": ieee_api_key,
        "session_days": session_days,
        "max_pdf_bytes": max_pdf_bytes,
        "max_attachment_bytes": max_attachment_bytes,
        "export_ttl_hours": export_ttl_hours,
    }
    update_runtime_settings(db, user, updates)
    return RedirectResponse("/admin/settings", status_code=303)


# =========================================================================
# 7. System Maintenance & Operations
# =========================================================================


@router.get("/admin/maintenance", response_class=HTMLResponse)
def admin_maintenance_page(
    request: Request,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    storage = get_storage_metrics(db, user)
    system_jobs = list_jobs_admin(db, user, kind_prefix="system.", limit=20)

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "user": user,
            "admin_tab": "maintenance",
            "storage": storage,
            "system_jobs": system_jobs,
            "csrf": login_session.csrf_token,
            "active_page": "admin",
        },
    )


@router.post("/admin/maintenance/reindex", dependencies=[Depends(require_csrf)])
def trigger_reindex_job(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    dispatch_maintenance_job(db, user, "system.reindex_all")
    return RedirectResponse("/admin/jobs", status_code=303)


@router.post("/admin/maintenance/check-objects", dependencies=[Depends(require_csrf)])
def trigger_check_objects_job(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    dispatch_maintenance_job(db, user, "system.check_objects")
    return RedirectResponse("/admin/jobs", status_code=303)


@router.post("/admin/maintenance/backup", dependencies=[Depends(require_csrf)])
def trigger_backup_job(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    dispatch_maintenance_job(db, user, "system.backup")
    return RedirectResponse("/admin/jobs", status_code=303)


@router.post("/admin/maintenance/recommend-tags", dependencies=[Depends(require_csrf)])
def trigger_recommend_tags_job(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    dispatch_maintenance_job(db, user, "system.recommend_tags_all")
    return RedirectResponse("/admin/jobs", status_code=303)


@router.get("/admin/maintenance/backups/{job_id}/download")
def download_backup_endpoint(
    job_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    path, filename = get_backup_artifact(db, user, job_id)
    return FileResponse(
        str(path),
        media_type="application/zip",
        filename=filename,
    )
