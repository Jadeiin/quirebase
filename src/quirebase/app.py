from __future__ import annotations

import json
import re
import secrets
import zipfile
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .bibliography import SUPPORTED_FORMATS, export_bibliography, parse_bibliography
from .config import get_settings
from .db import get_db
from .i18n import DEFAULT_LOCALE, translate
from .metadata_lookup import MetadataLookupError, MetadataNotFoundError, lookup_metadata
from .models import (
    Attachment,
    AuditEvent,
    DiscussionMessage,
    FileRevision,
    ImportBatch,
    Invitation,
    Item,
    ItemRead,
    ItemTag,
    Job,
    LoginSession,
    PdfAnnotation,
    PdfAnnotationSegment,
    Project,
    ProjectItem,
    ProjectMember,
    Tag,
    User,
)
from .pdf_service import extract_doi, job_payload, validate_pdf_container
from .permissions import (
    can_edit_annotation,
    can_edit_item,
    can_read_item,
    project_member,
    require_revision,
)
from .schemas import AnnotationCreate, AnnotationUpdate, ExportCreate
from .search import search_index
from .security import (
    check_login_throttle,
    clear_login_failures,
    create_login_session,
    current_login,
    current_user,
    hash_password,
    login_identity,
    record_login_failure,
    require_csrf,
    token_hash,
    verify_password,
)
from .storage import LocalObjectStore

if TYPE_CHECKING:
    from collections.abc import Sequence

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
templates.env.globals.update(locale=DEFAULT_LOCALE, t=translate)


def visible_items(user: User):
    query = select(Item)
    if user.role == "administrator":
        return query
    project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
    shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
    return query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))


def visible_projects(db: Session, user: User) -> list[Project]:
    query = select(Project).order_by(Project.name)
    if user.role != "administrator":
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return list(db.scalars(query).all())


def editable_projects(db: Session, user: User) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .join(ProjectMember)
            .where(
                ProjectMember.user_id == user.id,
                ProjectMember.role.in_(["owner", "editor"]),
            )
            .order_by(Project.name)
        ).all()
    )


def store_pdf_revision(db: Session, user: User, item: Item, pdf: UploadFile) -> FileRevision:
    return attach_staged_pdf(db, user, item, stage_pdf(pdf))


def stage_pdf(pdf: UploadFile) -> tuple[str, str, int, str]:
    if not pdf.filename or not pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "a PDF file is required")
    store = LocalObjectStore()
    try:
        key, digest, size = store.put_pdf(pdf.file, get_settings().max_pdf_bytes)
        validate_pdf_container(store.path(key))
    except ValueError as error:
        if "key" in locals():
            store.path(key).unlink(missing_ok=True)
        raise HTTPException(422, str(error)) from error
    return key, digest, size, Path(pdf.filename).name


def attach_staged_pdf(
    db: Session,
    user: User,
    item: Item,
    staged: tuple[str, str, int, str],
) -> FileRevision:
    key, digest, size, original_name = staged
    revision = FileRevision(
        item_id=item.id,
        object_key=key,
        sha256=digest,
        size=size,
        original_name=original_name,
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    db.add(
        Job(
            kind="pdf.inspect",
            payload=job_payload(revision_id=revision.id),
            idempotency_key=f"pdf.inspect:{revision.id}",
            owner_id=user.id,
        )
    )
    db.add(
        AuditEvent(
            actor_id=user.id,
            action="pdf.upload",
            target_type="file_revision",
            target_id=revision.id,
        )
    )
    return revision


def discard_staged_pdf(db: Session, object_key: str) -> None:
    if not db.scalar(select(FileRevision.id).where(FileRevision.object_key == object_key).limit(1)):
        LocalObjectStore().path(object_key).unlink(missing_ok=True)


def bibliography_response(items: list[Item], file_format: str) -> Response:
    export_format = "ris" if file_format == "endnote" else file_format
    if export_format not in SUPPORTED_FORMATS:
        raise HTTPException(422, "format must be bibtex, ris, or endnote")
    contents = export_bibliography(items, export_format)
    media_type = (
        "application/x-bibtex"
        if export_format == "bibtex"
        else "application/x-research-info-systems"
    )
    extension = {"bibtex": "bib", "ris": "ris", "endnote": "enw"}[file_format]
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="quirebase-export.{extension}"'},
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Quirebase", version="0.1.0")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=get_settings().allowed_host_list)
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics(user: User = Depends(current_user), db: Session = Depends(get_db)):
        if user.role != "administrator":
            raise HTTPException(404)
        lines = []
        for state, count in db.execute(
            select(Job.state, func.count()).group_by(Job.state).order_by(Job.state)
        ):
            lines.append(f'quirebase_jobs{{state="{state}"}} {count}')
        lines.append(f"quirebase_items {db.scalar(select(func.count()).select_from(Item)) or 0}")
        lines.append(
            f"quirebase_file_revisions {db.scalar(select(func.count()).select_from(FileRevision)) or 0}"
        )
        return "\n".join(lines) + "\n"

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        return templates.TemplateResponse(request, "login.html", {})

    @app.post("/login")
    def login(
        request: Request,
        username: str = Form(),
        password: str = Form(),
        db: Session = Depends(get_db),
    ):
        identity = login_identity(request, username)
        try:
            check_login_throttle(db, identity)
        except HTTPException:
            db.add(
                AuditEvent(
                    actor_id=None,
                    action="auth.login.throttled",
                    target_type="user",
                    target_id=None,
                    detail=json.dumps({"identity_hash": identity}),
                )
            )
            db.commit()
            raise
        user = db.scalar(select(User).where(User.username == username))
        if user is None or not user.active or not verify_password(user.password_hash, password):
            record_login_failure(db, identity)
            db.add(
                AuditEvent(
                    actor_id=None,
                    action="auth.login.failed",
                    target_type="user",
                    target_id=user.id if user else None,
                    detail=json.dumps({"identity_hash": identity}),
                )
            )
            db.commit()
            return templates.TemplateResponse(
                request, "login.html", {"error": "Invalid credentials"}, status_code=401
            )
        clear_login_failures(db, identity)
        login_session, raw = create_login_session(db, user)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="auth.login.succeeded",
                target_type="login_session",
                target_id=login_session.id,
                detail=json.dumps({"identity_hash": identity}),
            )
        )
        db.commit()
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

    @app.get("/accept-invitation/{token}", response_class=HTMLResponse)
    def accept_invitation_page(request: Request, token: str, db: Session = Depends(get_db)):
        invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
        valid = bool(
            invitation
            and invitation.accepted_at is None
            and invitation.expires_at.replace(tzinfo=UTC) > datetime.now(UTC)
        )
        return templates.TemplateResponse(
            request,
            "accept_invitation.html",
            {"token": token, "invitation": invitation if valid else None},
        )

    @app.post("/accept-invitation/{token}")
    def accept_invitation(token: str, password: str = Form(), db: Session = Depends(get_db)):
        invitation = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
        if (
            invitation is None
            or invitation.accepted_at is not None
            or invitation.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC)
        ):
            raise HTTPException(404)
        if db.scalar(select(User).where(User.username == invitation.username)):
            raise HTTPException(409, "username already exists")
        try:
            encoded = hash_password(password)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        user = User(username=invitation.username, password_hash=encoded, role=invitation.role)
        db.add(user)
        invitation.accepted_at = datetime.now(UTC)
        db.flush()
        db.add(
            AuditEvent(
                actor_id=user.id, action="invitation.accept", target_type="user", target_id=user.id
            )
        )
        db.commit()
        return RedirectResponse("/login", status_code=303)

    @app.get("/admin", response_class=HTMLResponse)
    def admin_page(
        request: Request,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        if user.role != "administrator":
            raise HTTPException(404)
        users = db.scalars(select(User).order_by(User.username)).all()
        invitations = db.scalars(select(Invitation).order_by(Invitation.created_at.desc())).all()
        failed_jobs = db.scalars(
            select(Job).where(Job.state == "failed").order_by(Job.updated_at.desc())
        ).all()
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "user": user,
                "users": users,
                "invitations": invitations,
                "failed_jobs": failed_jobs,
                "csrf": login.csrf_token,
                "active_page": "admin",
            },
        )

    @app.post(
        "/admin/invitations", dependencies=[Depends(require_csrf)], response_class=HTMLResponse
    )
    def create_invitation(
        request: Request,
        username: str = Form(),
        role: str = Form(default="member"),
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        if user.role != "administrator":
            raise HTTPException(404)
        normalized = username.strip()
        if not normalized or len(normalized) > 120 or role not in ("member", "administrator"):
            raise HTTPException(422, "invalid username or role")
        if db.scalar(select(User).where(User.username == normalized)) or db.scalar(
            select(Invitation).where(Invitation.username == normalized)
        ):
            raise HTTPException(409, "username already exists or is invited")
        raw = secrets.token_urlsafe(32)
        invitation = Invitation(
            token_hash=token_hash(raw),
            username=normalized,
            role=role,
            created_by=user.id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db.add(invitation)
        db.commit()
        return templates.TemplateResponse(
            request,
            "invitation_created.html",
            {
                "user": user,
                "csrf": login.csrf_token,
                "invitation": invitation,
                "invite_url": str(request.url_for("accept_invitation_page", token=raw)),
                "active_page": "admin",
            },
        )

    @app.post("/admin/jobs/{job_id}/retry", dependencies=[Depends(require_csrf)])
    def retry_job(
        job_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if user.role != "administrator":
            raise HTTPException(404)
        job = db.get(Job, job_id)
        if job is None or job.state != "failed":
            raise HTTPException(404)
        job.state = "pending"
        job.attempts = 0
        job.error = None
        job.lease_until = None
        db.commit()
        return RedirectResponse("/admin", status_code=303)

    @app.get("/account/sessions", response_class=HTMLResponse)
    def sessions_page(
        request: Request,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        sessions = db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.created_at.desc())
        ).all()
        return templates.TemplateResponse(
            request,
            "sessions.html",
            {
                "user": user,
                "login": login,
                "sessions": sessions,
                "csrf": login.csrf_token,
                "active_page": "sessions",
            },
        )

    @app.post("/account/sessions/{session_id}/revoke", dependencies=[Depends(require_csrf)])
    def revoke_session(
        session_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
    ):
        target = db.get(LoginSession, session_id)
        if target is None or target.user_id != user.id:
            raise HTTPException(404)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="auth.session.revoke",
                target_type="login_session",
                target_id=target.id,
            )
        )
        db.delete(target)
        db.commit()
        return RedirectResponse("/account/sessions", status_code=303)

    @app.post("/account/sessions/revoke-all", dependencies=[Depends(require_csrf)])
    def revoke_all_sessions(
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        count = db.scalar(
            select(func.count()).select_from(LoginSession).where(LoginSession.user_id == user.id)
        )
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="auth.sessions.revoke_all",
                target_type="user",
                target_id=user.id,
                detail=json.dumps({"revoked_sessions": count or 0}),
            )
        )
        db.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        db.commit()
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(get_settings().session_cookie)
        return response

    @app.post("/logout", dependencies=[Depends(require_csrf)])
    def logout(
        user: User = Depends(current_user),
        login_session: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="auth.logout",
                target_type="login_session",
                target_id=login_session.id,
            )
        )
        db.delete(login_session)
        db.commit()
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(get_settings().session_cookie)
        return response

    @app.get("/", response_class=HTMLResponse)
    def dashboard(
        request: Request,
        q: str = "",
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        if q.strip():
            return RedirectResponse(f"/library?{urlencode({'q': q.strip()})}", status_code=303)
        new_items = db.scalars(visible_items(user).order_by(Item.created_at.desc()).limit(10)).all()
        recent_items = db.execute(
            visible_items(user)
            .join(ItemRead, ItemRead.item_id == Item.id)
            .where(ItemRead.user_id == user.id)
            .with_only_columns(Item, ItemRead.last_read_at)
            .order_by(ItemRead.last_read_at.desc())
            .limit(10)
        ).all()
        projects = visible_projects(db, user)
        sessions = db.scalars(
            select(LoginSession)
            .where(LoginSession.user_id == user.id)
            .order_by(LoginSession.created_at.desc())
            .limit(10)
        ).all()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "user": user,
                "new_items": new_items,
                "recent_items": recent_items,
                "projects": projects,
                "sessions": sessions,
                "current_login": login,
                "csrf": login.csrf_token,
                "active_page": "dashboard",
            },
        )

    @app.get("/library", response_class=HTMLResponse)
    def library(
        request: Request,
        q: str = "",
        tag: str = "",
        project: str = "",
        year: str = "",
        keyword: str = "",
        author: str = "",
        page: int = 1,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        page = max(page, 1)
        per_page = 25
        item_query = visible_items(user)
        matching_ids = search_index(db).search(db, q) if q.strip() else None
        if matching_ids is not None:
            item_query = item_query.where(Item.id.in_(matching_ids))
        if tag:
            item_query = item_query.where(
                Item.id.in_(select(ItemTag.item_id).where(ItemTag.tag_id == tag))
            )
        if project:
            item_query = item_query.where(
                Item.id.in_(select(ProjectItem.item_id).where(ProjectItem.project_id == project))
            )
        if year:
            item_query = item_query.where(Item.publication_date.startswith(year))
        if keyword:
            item_query = item_query.where(Item.keywords.ilike(f"%{keyword}%"))
        if author:
            item_query = item_query.where(Item.authors.ilike(f"%{author}%"))
        total = db.scalar(select(func.count()).select_from(item_query.subquery())) or 0
        items = db.scalars(
            item_query
            .order_by(Item.updated_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        ).all()
        accessible_ids = visible_items(user).with_only_columns(Item.id).subquery()
        tags = db.scalars(
            select(Tag)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id.in_(select(accessible_ids.c.id)))
            .distinct()
            .order_by(Tag.name)
        ).all()
        dates = db.scalars(
            visible_items(user)
            .with_only_columns(Item.publication_date)
            .where(Item.publication_date.is_not(None))
        ).all()
        years = sorted(
            {value[:4] for value in dates if value and value[:4].isdigit()}, reverse=True
        )
        return templates.TemplateResponse(
            request,
            "library.html",
            {
                "user": user,
                "items": items,
                "projects": visible_projects(db, user),
                "editable_projects": editable_projects(db, user),
                "tags": tags,
                "years": years,
                "csrf": login.csrf_token,
                "active_page": "library",
                "filters": {
                    "q": q,
                    "tag": tag,
                    "project": project,
                    "year": year,
                    "keyword": keyword,
                    "author": author,
                },
                "page": page,
                "pages": max(1, (total + per_page - 1) // per_page),
                "total": total,
            },
        )

    @app.post("/library/bulk", dependencies=[Depends(require_csrf)])
    def library_bulk_action(
        action: str = Form(),
        item_ids: list[str] = Form(default=[]),
        project_id: str = Form(default=""),
        tag_name: str = Form(default=""),
        confirm_delete: str = Form(default=""),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        selected = [db.get(Item, item_id) for item_id in dict.fromkeys(item_ids)]
        items = [item for item in selected if item is not None and can_read_item(db, user, item.id)]
        if not items or len(items) != len(selected):
            raise HTTPException(422, "select one or more accessible papers")
        if action.startswith("export_"):
            return bibliography_response(items, action.removeprefix("export_"))
        if action == "download_pdfs":
            archive = BytesIO()
            used_names: set[str] = set()
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for item in items:
                    revision = db.scalar(
                        select(FileRevision)
                        .where(FileRevision.item_id == item.id)
                        .order_by(FileRevision.created_at.desc())
                        .limit(1)
                    )
                    if revision is None:
                        continue
                    filename = Path(revision.original_name).name
                    if filename in used_names:
                        filename = f"{item.id[:8]}-{filename}"
                    used_names.add(filename)
                    bundle.write(LocalObjectStore().path(revision.object_key), filename)
            db.add(
                AuditEvent(
                    actor_id=user.id,
                    action="library.bulk.download_pdfs",
                    target_type="item",
                    target_id=None,
                    detail=json.dumps({"item_ids": [item.id for item in items]}),
                )
            )
            db.commit()
            archive.seek(0)
            return StreamingResponse(
                archive,
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="quirebase-pdfs.zip"'},
            )
        if any(not can_edit_item(db, user, item.id) for item in items):
            raise HTTPException(403, "all selected papers must be editable")
        cleanup_keys: list[str] = []
        if action == "add_project":
            membership = project_member(db, user, project_id)
            if membership is None or membership.role not in ("owner", "editor"):
                raise HTTPException(422, "choose an editable project")
            for item in items:
                if db.get(ProjectItem, (project_id, item.id)) is None:
                    db.add(ProjectItem(project_id=project_id, item_id=item.id))
                    search_index(db).index_item(db, item.id)
        elif action == "add_tag":
            normalized = " ".join(tag_name.split())
            if not normalized or len(normalized) > 120:
                raise HTTPException(422, "enter a tag containing 1 to 120 characters")
            tag_record = db.scalar(select(Tag).where(Tag.name == normalized))
            if tag_record is None:
                tag_record = Tag(name=normalized, created_by=user.id)
                db.add(tag_record)
                db.flush()
            for item in items:
                if db.get(ItemTag, (item.id, tag_record.id)) is None:
                    db.add(ItemTag(item_id=item.id, tag_id=tag_record.id))
                    search_index(db).index_item(db, item.id)
        elif action == "delete_items":
            if confirm_delete != "delete":
                raise HTTPException(422, "confirm deletion of the selected papers")
            if user.role != "administrator" and any(item.created_by != user.id for item in items):
                raise HTTPException(403, "only paper owners can permanently delete papers")
            cleanup_keys = list(
                db.scalars(
                    select(FileRevision.object_key).where(
                        FileRevision.item_id.in_([item.id for item in items])
                    )
                ).all()
            )
            cleanup_keys.extend(
                db.scalars(
                    select(Attachment.object_key).where(
                        Attachment.item_id.in_([item.id for item in items])
                    )
                ).all()
            )
            for item in items:
                search_index(db).remove_item(db, item.id)
                db.delete(item)
        else:
            raise HTTPException(422, "unknown bulk action")
        db.add(
            AuditEvent(
                actor_id=user.id,
                action=f"library.bulk.{action}",
                target_type="item",
                target_id=None,
                detail=json.dumps({"item_ids": [item.id for item in items]}),
            )
        )
        db.commit()
        for object_key in cleanup_keys:
            with Session(db.bind) as cleanup_db:
                still_used = cleanup_db.scalar(
                    select(FileRevision.id).where(FileRevision.object_key == object_key).limit(1)
                ) or cleanup_db.scalar(
                    select(Attachment.id).where(Attachment.object_key == object_key).limit(1)
                )
            if not still_used:
                LocalObjectStore().path(object_key).unlink(missing_ok=True)
        return RedirectResponse("/library", status_code=303)

    @app.post("/projects", dependencies=[Depends(require_csrf)])
    def create_project(
        name: str = Form(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not name.strip():
            raise HTTPException(422, "project name is required")
        project = Project(name=name.strip(), created_by=user.id)
        db.add(project)
        db.flush()
        db.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner"))
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="project.create",
                target_type="project",
                target_id=project.id,
            )
        )
        db.commit()
        return RedirectResponse(f"/projects/{project.id}", status_code=303)

    @app.get("/projects", response_class=HTMLResponse)
    def projects_page(
        request: Request,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        projects = db.execute(
            select(Project, ProjectMember.role, func.count(ProjectItem.item_id))
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .outerjoin(ProjectItem, ProjectItem.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .group_by(Project.id, ProjectMember.role)
            .order_by(Project.name)
        ).all()
        return templates.TemplateResponse(
            request,
            "projects.html",
            {
                "user": user,
                "projects": projects,
                "csrf": login.csrf_token,
                "active_page": "projects",
            },
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project_page(
        request: Request,
        project_id: str,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        membership = project_member(db, user, project_id)
        if membership is None and user.role != "administrator":
            raise HTTPException(404)
        project = db.get(Project, project_id)
        if project is None:
            raise HTTPException(404)
        members = db.execute(
            select(User, ProjectMember.role)
            .join(ProjectMember, ProjectMember.user_id == User.id)
            .where(ProjectMember.project_id == project_id)
            .order_by(User.username)
        ).all()
        items = db.scalars(
            select(Item)
            .join(ProjectItem, ProjectItem.item_id == Item.id)
            .where(ProjectItem.project_id == project_id)
            .order_by(Item.updated_at.desc())
        ).all()
        return templates.TemplateResponse(
            request,
            "project.html",
            {
                "user": user,
                "project": project,
                "membership": membership,
                "members": members,
                "items": items,
                "csrf": login.csrf_token,
                "active_page": "projects",
            },
        )

    @app.post("/projects/{project_id}/members", dependencies=[Depends(require_csrf)])
    def add_project_member(
        project_id: str,
        username: str = Form(),
        role: str = Form(default="viewer"),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        membership = project_member(db, user, project_id)
        if membership is None or membership.role != "owner":
            raise HTTPException(404)
        if role not in ("owner", "editor", "viewer"):
            raise HTTPException(422, "invalid project role")
        target = db.scalar(
            select(User).where(User.username == username.strip(), User.active.is_(True))
        )
        if target is None:
            raise HTTPException(404, "user not found")
        existing = db.get(ProjectMember, (project_id, target.id))
        if existing:
            existing.role = role
        else:
            db.add(ProjectMember(project_id=project_id, user_id=target.id, role=role))
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="project.member.set",
                target_type="project",
                target_id=project_id,
                detail=json.dumps({"user_id": target.id, "role": role}),
            )
        )
        db.commit()
        return RedirectResponse(f"/projects/{project_id}", status_code=303)

    @app.post(
        "/projects/{project_id}/members/{member_id}/remove", dependencies=[Depends(require_csrf)]
    )
    def remove_project_member(
        project_id: str,
        member_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        actor = project_member(db, user, project_id)
        target = db.get(ProjectMember, (project_id, member_id))
        if actor is None or actor.role != "owner" or target is None:
            raise HTTPException(404)
        owner_count = db.scalar(
            select(func.count())
            .select_from(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.role == "owner")
        )
        if target.role == "owner" and (owner_count or 0) <= 1:
            raise HTTPException(409, "a project must retain an owner")
        db.delete(target)
        db.commit()
        return RedirectResponse(f"/projects/{project_id}", status_code=303)

    @app.post("/items", dependencies=[Depends(require_csrf)])
    def create_item(
        title: str = Form(),
        abstract: str = Form(default=""),
        authors: str = Form(default=""),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not title.strip():
            raise HTTPException(422, "title is required")
        item = Item(
            title=title.strip(),
            abstract=abstract.strip() or None,
            authors=authors.strip() or None,
            created_by=user.id,
        )
        db.add(item)
        db.flush()
        search_index(db).index_item(db, item.id)
        db.add(
            AuditEvent(
                actor_id=user.id, action="item.create", target_type="item", target_id=item.id
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item.id}", status_code=303)

    @app.get("/bibliography/import", response_class=HTMLResponse)
    def import_page(
        request: Request,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
    ):
        return templates.TemplateResponse(
            request,
            "import.html",
            {"user": user, "csrf": login.csrf_token, "active_page": "import"},
        )

    @app.get("/tools", response_class=HTMLResponse)
    def tools_page(
        request: Request,
        mode: str = "",
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        if mode not in ("", "doi", "pdf", "title", "similar"):
            raise HTTPException(404)
        limit = 500 if mode == "similar" else 2000
        items = list(db.scalars(visible_items(user).order_by(Item.title).limit(limit)).all())
        groups: list[list[Item]] = []
        if mode:
            buckets: dict[str, list[Item]] = {}
            if mode == "doi":
                for item in items:
                    key = (item.doi or "").strip().lower()
                    if key:
                        buckets.setdefault(key, []).append(item)
            elif mode == "pdf":
                revisions = db.execute(
                    select(FileRevision.item_id, FileRevision.sha256).where(
                        FileRevision.item_id.in_([item.id for item in items])
                    )
                ).all()
                item_map = {item.id: item for item in items}
                for item_id, digest in revisions:
                    group = buckets.setdefault(digest, [])
                    if all(item.id != item_id for item in group):
                        group.append(item_map[item_id])
            else:
                normalize = lambda title: re.sub(r"[^\w]+", " ", title.casefold()).strip()
                if mode == "title":
                    for item in items:
                        buckets.setdefault(normalize(item.title), []).append(item)
                else:
                    remaining = items.copy()
                    while remaining:
                        anchor = remaining.pop(0)
                        key = normalize(anchor.title)
                        matches = [anchor]
                        for candidate in remaining.copy():
                            if (
                                SequenceMatcher(None, key, normalize(candidate.title)).ratio()
                                >= 0.9
                            ):
                                matches.append(candidate)
                                remaining.remove(candidate)
                        if len(matches) > 1:
                            groups.append(matches)
            if mode != "similar":
                groups = [group for group in buckets.values() if len({row.id for row in group}) > 1]
        accessible_ids = visible_items(user).with_only_columns(Item.id).subquery()
        tags = db.execute(
            select(Tag, func.count(ItemTag.item_id))
            .outerjoin(
                ItemTag,
                and_(ItemTag.tag_id == Tag.id, ItemTag.item_id.in_(select(accessible_ids.c.id))),
            )
            .group_by(Tag.id)
            .having(func.count(ItemTag.item_id) > 0)
            .order_by(Tag.name)
        ).all()
        return templates.TemplateResponse(
            request,
            "tools.html",
            {
                "user": user,
                "csrf": login.csrf_token,
                "mode": mode,
                "groups": groups,
                "tags": tags,
                "active_page": "tools",
            },
        )

    @app.post("/tools/tags/{tag_id}", dependencies=[Depends(require_csrf)])
    def rename_tag(
        tag_id: str,
        name: str = Form(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        tag = db.get(Tag, tag_id)
        normalized = " ".join(name.split())
        if tag is None or (tag.created_by != user.id and user.role != "administrator"):
            raise HTTPException(404)
        if not normalized or len(normalized) > 120:
            raise HTTPException(422, "tag must contain 1 to 120 characters")
        if db.scalar(select(Tag.id).where(Tag.name == normalized, Tag.id != tag.id)):
            raise HTTPException(409, "tag name already exists")
        tag.name = normalized
        item_ids = list(db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)).all())
        for item_id in item_ids:
            search_index(db).index_item(db, item_id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="tag.rename",
                target_type="tag",
                target_id=tag.id,
            )
        )
        db.commit()
        return RedirectResponse("/tools#tags", status_code=303)

    @app.post("/tools/tags/{tag_id}/delete", dependencies=[Depends(require_csrf)])
    def delete_tag(
        tag_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        tag = db.get(Tag, tag_id)
        if tag is None or (tag.created_by != user.id and user.role != "administrator"):
            raise HTTPException(404)
        item_ids = list(db.scalars(select(ItemTag.item_id).where(ItemTag.tag_id == tag.id)).all())
        db.delete(tag)
        db.flush()
        for item_id in item_ids:
            search_index(db).index_item(db, item_id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="tag.delete",
                target_type="tag",
                target_id=tag_id,
            )
        )
        db.commit()
        return RedirectResponse("/tools#tags", status_code=303)

    @app.post("/imports/pdf/published", dependencies=[Depends(require_csrf)])
    def import_published_pdf(
        doi: str = Form(default=""),
        pdf: UploadFile = File(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        staged = stage_pdf(pdf)
        detected_doi = extract_doi(LocalObjectStore().path(staged[0]))
        identifier = doi.strip() or detected_doi
        if not identifier:
            discard_staged_pdf(db, staged[0])
            raise HTTPException(
                422, "no DOI was found in the PDF; enter one manually or import it as unpublished"
            )
        try:
            _identifier, record = lookup_metadata(identifier, "doi")
        except ValueError as error:
            discard_staged_pdf(db, staged[0])
            raise HTTPException(422, str(error)) from error
        except MetadataNotFoundError as error:
            discard_staged_pdf(db, staged[0])
            raise HTTPException(404, str(error)) from error
        except MetadataLookupError as error:
            discard_staged_pdf(db, staged[0])
            raise HTTPException(502, str(error)) from error
        item = Item(created_by=user.id, **record)
        db.add(item)
        db.flush()
        attach_staged_pdf(db, user, item, staged)
        search_index(db).index_item(db, item.id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="import.pdf.published",
                target_type="item",
                target_id=item.id,
                detail=json.dumps({
                    "doi": item.doi,
                    "detected_automatically": not bool(doi.strip()),
                }),
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item.id}", status_code=303)

    @app.post("/imports/pdf/unpublished", dependencies=[Depends(require_csrf)])
    def import_unpublished_pdf(
        title: str = Form(),
        authors: str = Form(default=""),
        abstract: str = Form(default=""),
        keywords: str = Form(default=""),
        pdf: UploadFile = File(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not title.strip():
            raise HTTPException(422, "title is required")
        item = Item(
            title=title.strip(),
            authors=authors.strip() or None,
            abstract=abstract.strip() or None,
            keywords=keywords.strip() or None,
            reference_type="unpublished",
            created_by=user.id,
        )
        db.add(item)
        db.flush()
        store_pdf_revision(db, user, item, pdf)
        search_index(db).index_item(db, item.id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="import.pdf.unpublished",
                target_type="item",
                target_id=item.id,
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item.id}", status_code=303)

    @app.post("/bibliography/preview", dependencies=[Depends(require_csrf)])
    def preview_import(
        request: Request,
        bibliography: UploadFile = File(),
        file_format: str = Form(),
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        if file_format not in SUPPORTED_FORMATS:
            raise HTTPException(422, "format must be bibtex or ris")
        raw = bibliography.file.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(413, "bibliography files are limited to 5 MiB")
        try:
            contents = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(422, "bibliography must be UTF-8") from error
        records, errors = parse_bibliography(contents, file_format)
        batch = ImportBatch(
            owner_id=user.id,
            file_format=file_format,
            records=json.dumps(records, ensure_ascii=False),
            errors=json.dumps(errors, ensure_ascii=False),
        )
        db.add(batch)
        db.commit()
        return templates.TemplateResponse(
            request,
            "import_preview.html",
            {
                "user": user,
                "csrf": login.csrf_token,
                "batch": batch,
                "records": records,
                "errors": errors,
                "active_page": "import",
            },
        )

    @app.post("/metadata/preview", dependencies=[Depends(require_csrf)])
    def preview_online_metadata(
        request: Request,
        identifier: str = Form(),
        provider: str = Form(default="auto"),
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        try:
            parsed, record = lookup_metadata(identifier, provider)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except MetadataNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except MetadataLookupError as error:
            raise HTTPException(502, str(error)) from error
        batch = ImportBatch(
            owner_id=user.id,
            file_format=f"metadata:{parsed.provider}",
            records=json.dumps([record], ensure_ascii=False),
            errors="[]",
        )
        db.add(batch)
        db.flush()
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="metadata.lookup",
                target_type="import_batch",
                target_id=batch.id,
                detail=json.dumps({"provider": parsed.provider}),
            )
        )
        db.commit()
        return templates.TemplateResponse(
            request,
            "import_preview.html",
            {
                "user": user,
                "csrf": login.csrf_token,
                "batch": batch,
                "records": [record],
                "errors": [],
                "active_page": "import",
            },
        )

    @app.post("/bibliography/import/{batch_id}", dependencies=[Depends(require_csrf)])
    def commit_import(
        batch_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        batch = db.get(ImportBatch, batch_id)
        if batch is None or batch.owner_id != user.id:
            raise HTTPException(404)
        errors = json.loads(batch.errors)
        if errors:
            raise HTTPException(409, "the preview contains errors")
        records = json.loads(batch.records)
        for record in records:
            item = Item(created_by=user.id, **record)
            db.add(item)
            db.flush()
            search_index(db).index_item(db, item.id)
            db.add(
                AuditEvent(
                    actor_id=user.id,
                    action="bibliography.import",
                    target_type="item",
                    target_id=item.id,
                    detail=json.dumps({"format": batch.file_format}),
                )
            )
        db.delete(batch)
        db.commit()
        return RedirectResponse("/", status_code=303)

    @app.get("/bibliography/export")
    def export_items(
        file_format: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        query = select(Item).order_by(Item.updated_at.desc())
        if user.role != "administrator":
            project_ids = select(ProjectMember.project_id).where(ProjectMember.user_id == user.id)
            shared_ids = select(ProjectItem.item_id).where(ProjectItem.project_id.in_(project_ids))
            query = query.where(or_(Item.created_by == user.id, Item.id.in_(shared_ids)))
        return bibliography_response(list(db.scalars(query).all()), file_format)

    def render_item_workspace(
        request: Request,
        item_id: str,
        section: str,
        user: User,
        login: LoginSession,
        db: Session,
    ):
        sections = {"summary", "metadata", "files", "organize", "annotations", "discussion"}
        if section not in sections:
            raise HTTPException(404)
        if not can_read_item(db, user, item_id):
            raise HTTPException(404)
        item = db.scalar(
            select(Item).options(selectinload(Item.revisions)).where(Item.id == item_id)
        )
        if item is None:
            raise HTTPException(404)
        read = db.get(ItemRead, (user.id, item.id))
        if read is None:
            db.add(ItemRead(user_id=user.id, item_id=item.id))
        else:
            read.last_read_at = datetime.now(UTC)
        db.commit()
        revisions = sorted(item.revisions, key=lambda row: row.created_at, reverse=True)
        memberships = db.execute(
            select(Project, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(ProjectMember.user_id == user.id)
            .order_by(Project.name)
        ).all()
        assigned = set(
            db.scalars(select(ProjectItem.project_id).where(ProjectItem.item_id == item_id)).all()
        )
        tags = db.scalars(
            select(Tag)
            .join(ItemTag, ItemTag.tag_id == Tag.id)
            .where(ItemTag.item_id == item_id)
            .order_by(Tag.name)
        ).all()
        messages = db.scalars(
            select(DiscussionMessage)
            .options(selectinload(DiscussionMessage.author))
            .where(DiscussionMessage.item_id == item_id)
            .order_by(DiscussionMessage.created_at)
        ).all()
        attachments = db.scalars(
            select(Attachment).where(Attachment.item_id == item_id).order_by(Attachment.created_at)
        ).all()
        revision_ids = [revision.id for revision in revisions]
        annotations: Sequence[object] = ()
        if revision_ids:
            member_projects = select(ProjectMember.project_id).where(
                ProjectMember.user_id == user.id
            )
            annotations = db.execute(
                select(PdfAnnotation, FileRevision, User)
                .join(FileRevision, FileRevision.id == PdfAnnotation.file_revision_id)
                .join(User, User.id == PdfAnnotation.author_id)
                .where(
                    PdfAnnotation.file_revision_id.in_(revision_ids),
                    PdfAnnotation.deleted_at.is_(None),
                    or_(
                        and_(
                            PdfAnnotation.scope == "private",
                            PdfAnnotation.author_id == user.id,
                        ),
                        and_(
                            PdfAnnotation.scope == "project",
                            PdfAnnotation.project_id.in_(member_projects),
                        ),
                    ),
                )
                .order_by(PdfAnnotation.updated_at.desc())
            ).all()
        return templates.TemplateResponse(
            request,
            "item.html",
            {
                "user": user,
                "item": item,
                "revisions": revisions,
                "memberships": memberships,
                "assigned": assigned,
                "tags": tags,
                "messages": messages,
                "attachments": attachments,
                "annotations": annotations,
                "can_edit": can_edit_item(db, user, item_id),
                "csrf": login.csrf_token,
                "active_page": "library",
                "item_section": section,
            },
        )

    @app.get("/items/{item_id}", response_class=HTMLResponse)
    def item_page(
        request: Request,
        item_id: str,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        return render_item_workspace(request, item_id, "summary", user, login, db)

    @app.get("/items/{item_id}/{section}", response_class=HTMLResponse)
    def item_section_page(
        request: Request,
        item_id: str,
        section: str,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        return render_item_workspace(request, item_id, section, user, login, db)

    @app.get("/documents/{item_id}/citation")
    def export_item(
        item_id: str,
        file_format: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_read_item(db, user, item_id):
            raise HTTPException(404)
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(404)
        return bibliography_response([item], file_format)

    @app.post("/items/{item_id}/edit", dependencies=[Depends(require_csrf)])
    def edit_item(
        item_id: str,
        version: int = Form(),
        title: str = Form(),
        abstract: str = Form(default=""),
        authors: str = Form(default=""),
        editors: str = Form(default=""),
        keywords: str = Form(default=""),
        publication_date: str = Form(default=""),
        publication_title: str = Form(default=""),
        doi: str = Form(default=""),
        reference_type: str = Form(default=""),
        identifiers: str = Form(default=""),
        custom_fields: str = Form(default=""),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_edit_item(db, user, item_id):
            raise HTTPException(404)
        if not title.strip():
            raise HTTPException(422, "title is required")
        if custom_fields.strip():
            try:
                parsed_custom = json.loads(custom_fields)
            except json.JSONDecodeError as error:
                raise HTTPException(422, "custom fields must be valid JSON") from error
            if not isinstance(parsed_custom, dict):
                raise HTTPException(422, "custom fields must be a JSON object")
        if identifiers.strip():
            try:
                parsed_identifiers = json.loads(identifiers)
            except json.JSONDecodeError as error:
                raise HTTPException(422, "identifiers must be valid JSON") from error
            if not isinstance(parsed_identifiers, dict):
                raise HTTPException(422, "identifiers must be a JSON object")
        updated_id = db.scalar(
            update(Item)
            .where(Item.id == item_id, Item.version == version)
            .values(
                title=title.strip(),
                abstract=abstract.strip() or None,
                authors=authors.strip() or None,
                editors=editors.strip() or None,
                keywords=keywords.strip() or None,
                publication_date=publication_date.strip() or None,
                publication_title=publication_title.strip() or None,
                doi=doi.strip() or None,
                reference_type=reference_type.strip() or None,
                identifiers=json.dumps(parsed_identifiers, ensure_ascii=False)
                if identifiers.strip()
                else None,
                custom_fields=json.dumps(parsed_custom, ensure_ascii=False)
                if custom_fields.strip()
                else None,
                version=Item.version + 1,
                updated_at=datetime.now(UTC),
            )
            .returning(Item.id)
        )
        if updated_id is None:
            db.rollback()
            current = db.get(Item, item_id)
            raise HTTPException(409, {"version": current.version if current else None})
        db.flush()
        db.expire_all()
        item = db.get(Item, item_id)
        if item is None:
            raise HTTPException(404)
        search_index(db).index_item(db, item.id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="item.update",
                target_type="item",
                target_id=item.id,
                detail=json.dumps({"version": version + 1}),
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item.id}/metadata", status_code=303)

    @app.post("/items/{item_id}/attachments", dependencies=[Depends(require_csrf)])
    def upload_attachment(
        item_id: str,
        attachment: UploadFile = File(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_edit_item(db, user, item_id) or not attachment.filename:
            raise HTTPException(404)
        try:
            key, digest, size = LocalObjectStore().put_attachment(
                attachment.file, get_settings().max_attachment_bytes
            )
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        record = Attachment(
            item_id=item_id,
            object_key=key,
            sha256=digest,
            size=size,
            mime_type=(attachment.content_type or "application/octet-stream")[:100],
            original_name=Path(attachment.filename).name[:255],
            created_by=user.id,
        )
        db.add(record)
        db.flush()
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="attachment.upload",
                target_type="attachment",
                target_id=record.id,
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item_id}/files", status_code=303)

    @app.get("/items/{item_id}/attachments/{attachment_id}")
    def download_attachment(
        item_id: str,
        attachment_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        record = db.get(Attachment, attachment_id)
        if record is None or record.item_id != item_id or not can_read_item(db, user, item_id):
            raise HTTPException(404)
        return FileResponse(
            LocalObjectStore().path(record.object_key),
            media_type="application/octet-stream",
            filename=record.original_name,
            content_disposition_type="attachment",
        )

    @app.post("/items/{item_id}/tags", dependencies=[Depends(require_csrf)])
    def add_tag(
        item_id: str,
        name: str = Form(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_edit_item(db, user, item_id):
            raise HTTPException(404)
        normalized = " ".join(name.split())
        if not normalized or len(normalized) > 120:
            raise HTTPException(422, "tag must contain 1 to 120 characters")
        tag = db.scalar(select(Tag).where(Tag.name == normalized))
        if tag is None:
            tag = Tag(name=normalized, created_by=user.id)
            db.add(tag)
            db.flush()
        if db.get(ItemTag, (item_id, tag.id)) is None:
            db.add(ItemTag(item_id=item_id, tag_id=tag.id))
            db.flush()
            search_index(db).index_item(db, item_id)
            db.add(
                AuditEvent(
                    actor_id=user.id, action="tag.add", target_type="item", target_id=item_id
                )
            )
            db.commit()
        return RedirectResponse(f"/items/{item_id}/organize", status_code=303)

    @app.post("/items/{item_id}/tags/{tag_id}/remove", dependencies=[Depends(require_csrf)])
    def remove_tag(
        item_id: str,
        tag_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_edit_item(db, user, item_id):
            raise HTTPException(404)
        assignment = db.get(ItemTag, (item_id, tag_id))
        if assignment:
            db.delete(assignment)
            db.flush()
            search_index(db).index_item(db, item_id)
            db.commit()
        return RedirectResponse(f"/items/{item_id}/organize", status_code=303)

    @app.post("/items/{item_id}/discussion", dependencies=[Depends(require_csrf)])
    def add_discussion_message(
        item_id: str,
        body: str = Form(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        if not can_read_item(db, user, item_id):
            raise HTTPException(404)
        content = body.strip()
        if not content or len(content) > 20_000:
            raise HTTPException(422, "message must contain 1 to 20000 characters")
        message = DiscussionMessage(item_id=item_id, author_id=user.id, body=content)
        db.add(message)
        db.flush()
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="discussion.create",
                target_type="discussion",
                target_id=message.id,
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)

    @app.post(
        "/items/{item_id}/discussion/{message_id}/delete", dependencies=[Depends(require_csrf)]
    )
    def delete_discussion_message(
        item_id: str,
        message_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        message = db.get(DiscussionMessage, message_id)
        if (
            message is None
            or message.item_id != item_id
            or (message.author_id != user.id and user.role != "administrator")
        ):
            raise HTTPException(404)
        db.delete(message)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="discussion.delete",
                target_type="discussion",
                target_id=message_id,
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)

    @app.post("/items/{item_id}/projects/{project_id}", dependencies=[Depends(require_csrf)])
    def add_item_to_project(
        item_id: str,
        project_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        item = db.get(Item, item_id)
        membership = project_member(db, user, project_id)
        if (
            item is None
            or not can_read_item(db, user, item_id)
            or membership is None
            or membership.role not in ("owner", "editor")
        ):
            raise HTTPException(404)
        if db.get(ProjectItem, (project_id, item_id)) is None:
            db.add(ProjectItem(project_id=project_id, item_id=item_id))
            db.flush()
            search_index(db).index_item(db, item_id)
            db.add(
                AuditEvent(
                    actor_id=user.id,
                    action="project.item.add",
                    target_type="item",
                    target_id=item_id,
                    detail=json.dumps({"project_id": project_id}),
                )
            )
            db.commit()
        return RedirectResponse(f"/items/{item_id}/organize", status_code=303)

    @app.post("/items/{item_id}/projects/{project_id}/remove", dependencies=[Depends(require_csrf)])
    def remove_item_from_project(
        item_id: str,
        project_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        membership = project_member(db, user, project_id)
        assignment = db.get(ProjectItem, (project_id, item_id))
        if (
            assignment is None
            or not can_read_item(db, user, item_id)
            or membership is None
            or membership.role not in ("owner", "editor")
        ):
            raise HTTPException(404)
        db.delete(assignment)
        db.flush()
        search_index(db).index_item(db, item_id)
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="project.item.remove",
                target_type="item",
                target_id=item_id,
                detail=json.dumps({"project_id": project_id}),
            )
        )
        db.commit()
        return RedirectResponse(f"/items/{item_id}/organize", status_code=303)

    @app.post("/items/{item_id}/pdf", dependencies=[Depends(require_csrf)])
    def upload_pdf(
        item_id: str,
        pdf: UploadFile = File(),
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        item = db.get(Item, item_id)
        if item is None or not can_edit_item(db, user, item_id):
            raise HTTPException(404)
        store_pdf_revision(db, user, item, pdf)
        db.commit()
        return RedirectResponse(f"/items/{item.id}/files", status_code=303)

    @app.get("/items/{item_id}/pdf/{revision_id}", response_class=HTMLResponse)
    def pdf_viewer(
        request: Request,
        item_id: str,
        revision_id: str,
        user: User = Depends(current_user),
        login: LoginSession = Depends(current_login),
        db: Session = Depends(get_db),
    ):
        revision = require_revision(db, user, revision_id)
        if revision.item_id != item_id:
            raise HTTPException(404)
        projects = db.scalars(
            select(Project)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .join(ProjectItem, ProjectItem.project_id == Project.id)
            .where(ProjectMember.user_id == user.id, ProjectItem.item_id == item_id)
            .order_by(Project.name)
        ).all()
        return templates.TemplateResponse(
            request,
            "pdf.html",
            {
                "user": user,
                "item": revision.item,
                "revision": revision,
                "csrf": login.csrf_token,
                "projects": projects,
                "active_page": "library",
            },
        )

    @app.get("/documents/{item_id}/revisions/{revision_id}/content")
    def pdf_content(
        request: Request,
        item_id: str,
        revision_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        revision = require_revision(db, user, revision_id)
        if revision.item_id != item_id:
            raise HTTPException(404)
        path = LocalObjectStore().path(revision.object_key)
        return ranged_file(request, path, revision.sha256, revision.original_name)

    @app.get("/documents/{item_id}/annotations")
    def list_annotations(
        item_id: str,
        revision_id: str,
        project_id: str | None = None,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        revision = require_revision(db, user, revision_id)
        if revision.item_id != item_id:
            raise HTTPException(404)
        scopes = [and_(PdfAnnotation.scope == "private", PdfAnnotation.author_id == user.id)]
        if project_id:
            if (
                project_member(db, user, project_id) is None
                or db.get(ProjectItem, (project_id, item_id)) is None
            ):
                raise HTTPException(404)
            scopes.append(
                and_(PdfAnnotation.scope == "project", PdfAnnotation.project_id == project_id)
            )
        records = db.scalars(
            select(PdfAnnotation)
            .options(selectinload(PdfAnnotation.segments))
            .where(
                PdfAnnotation.file_revision_id == revision_id,
                PdfAnnotation.deleted_at.is_(None),
                or_(*scopes),
            )
            .order_by(PdfAnnotation.created_at)
        ).all()
        return {"annotations": [annotation_json(row, user.id) for row in records]}

    @app.post("/documents/{item_id}/annotations", dependencies=[Depends(require_csrf)])
    def create_annotation(
        item_id: str,
        data: AnnotationCreate,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        revision = require_revision(db, user, data.revision_id)
        if revision.item_id != item_id:
            raise HTTPException(404)
        if data.scope == "project" and (
            project_member(db, user, data.project_id) is None
            or db.get(ProjectItem, (data.project_id, item_id)) is None
        ):
            raise HTTPException(404)
        validate_segments(data, revision)
        record = PdfAnnotation(
            file_revision_id=data.revision_id,
            author_id=user.id,
            kind=data.kind,
            scope=data.scope,
            project_id=data.project_id,
            color=data.color,
            body=data.body,
            selected_text=data.selected_text,
        )
        for ordinal, segment in enumerate(data.segments):
            values: Sequence[float | None] = segment.quad_points or [None] * 8
            record.segments.append(
                PdfAnnotationSegment(
                    page_index=segment.page_index,
                    ordinal=ordinal,
                    x1=values[0],
                    y1=values[1],
                    x2=values[2],
                    y2=values[3],
                    x3=values[4],
                    y3=values[5],
                    x4=values[6],
                    y4=values[7],
                    anchor_x=segment.anchor_x,
                    anchor_y=segment.anchor_y,
                )
            )
        db.add(record)
        db.flush()
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="annotation.create",
                target_type="pdf_annotation",
                target_id=record.id,
            )
        )
        db.commit()
        return JSONResponse(annotation_json(record, user.id), status_code=201)

    @app.patch(
        "/documents/{item_id}/annotations/{annotation_id}", dependencies=[Depends(require_csrf)]
    )
    def update_annotation(
        item_id: str,
        annotation_id: str,
        data: AnnotationUpdate,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        record = db.get(PdfAnnotation, annotation_id)
        record_revision = db.get(FileRevision, record.file_revision_id) if record else None
        if (
            record is None
            or record.deleted_at
            or not can_read_item(db, user, item_id)
            or record_revision is None
            or record_revision.item_id != item_id
            or not can_edit_annotation(db, user, record)
        ):
            raise HTTPException(404)
        if record.version != data.version:
            raise HTTPException(409, {"version": record.version})
        if data.scope is not None:
            record.scope = data.scope
            record.project_id = data.project_id if data.scope == "project" else None
            if record.scope == "project" and (
                project_member(db, user, record.project_id) is None
                or db.get(ProjectItem, (record.project_id, item_id)) is None
            ):
                raise HTTPException(404)
        if data.color is not None:
            record.color = data.color
        if data.body is not None:
            record.body = data.body
        record.version += 1
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="annotation.update",
                target_type="pdf_annotation",
                target_id=record.id,
            )
        )
        db.commit()
        return annotation_json(record, user.id)

    @app.delete(
        "/documents/{item_id}/annotations/{annotation_id}", dependencies=[Depends(require_csrf)]
    )
    def delete_annotation(
        item_id: str,
        annotation_id: str,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        record = db.get(PdfAnnotation, annotation_id)
        record_revision = db.get(FileRevision, record.file_revision_id) if record else None
        if (
            record is None
            or record.deleted_at
            or not can_read_item(db, user, item_id)
            or record_revision is None
            or record_revision.item_id != item_id
            or not can_edit_annotation(db, user, record)
        ):
            raise HTTPException(404)
        record.deleted_at = datetime.now(UTC)
        record.version += 1
        db.add(
            AuditEvent(
                actor_id=user.id,
                action="annotation.delete",
                target_type="pdf_annotation",
                target_id=record.id,
            )
        )
        db.commit()
        return Response(status_code=204)

    @app.post("/documents/{item_id}/annotation-exports", dependencies=[Depends(require_csrf)])
    def create_export(
        item_id: str,
        data: ExportCreate,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ):
        revision = require_revision(db, user, data.revision_id)
        if revision.item_id != item_id:
            raise HTTPException(404)
        if data.project_id and (
            project_member(db, user, data.project_id) is None
            or db.get(ProjectItem, (data.project_id, item_id)) is None
        ):
            raise HTTPException(404)
        job = Job(
            kind="pdf.export_annotations",
            payload=job_payload(
                revision_id=data.revision_id,
                project_id=data.project_id,
                include_private=data.include_private,
            ),
            idempotency_key=f"pdf.export:{user.id}:{data.revision_id}:{data.project_id}:{datetime.now(UTC).isoformat()}",
            owner_id=user.id,
        )
        db.add(job)
        db.commit()
        return JSONResponse({"id": job.id, "state": job.state}, status_code=202)

    @app.get("/annotation-exports/{job_id}")
    def export_status(
        job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
    ):
        job = db.get(Job, job_id)
        if job is None or job.kind != "pdf.export_annotations" or job.owner_id != user.id:
            raise HTTPException(404)
        return {"id": job.id, "state": job.state, "error": job.error}

    @app.get("/annotation-exports/{job_id}/content")
    def export_content(
        job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)
    ):
        job = db.get(Job, job_id)
        if (
            job is None
            or job.kind != "pdf.export_annotations"
            or job.owner_id != user.id
            or job.state != "succeeded"
        ):
            raise HTTPException(404)
        result = json.loads(job.result or "{}")
        payload = json.loads(job.payload)
        require_revision(db, user, payload["revision_id"])
        if payload.get("project_id"):
            revision = require_revision(db, user, payload["revision_id"])
            if (
                project_member(db, user, payload["project_id"]) is None
                or db.get(ProjectItem, (payload["project_id"], revision.item_id)) is None
            ):
                raise HTTPException(404)
        path = get_settings().export_dir / result["filename"]
        return FileResponse(path, media_type="application/pdf", filename="annotated.pdf")

    return app


def annotation_json(record: PdfAnnotation, current_user_id: str) -> dict:
    return {
        "id": record.id,
        "revision_id": record.file_revision_id,
        "kind": record.kind,
        "scope": record.scope,
        "project_id": record.project_id,
        "color": record.color,
        "body": record.body,
        "selected_text": record.selected_text,
        "version": record.version,
        "mine": record.author_id == current_user_id,
        "segments": [
            {
                "page_index": segment.page_index,
                "quad_points": [
                    segment.x1,
                    segment.y1,
                    segment.x2,
                    segment.y2,
                    segment.x3,
                    segment.y3,
                    segment.x4,
                    segment.y4,
                ]
                if segment.x1 is not None
                else None,
                "anchor_x": segment.anchor_x,
                "anchor_y": segment.anchor_y,
            }
            for segment in record.segments
        ],
    }


def validate_segments(data: AnnotationCreate, revision: FileRevision) -> None:
    if revision.page_count is None or revision.processing_state != "ready":
        raise HTTPException(409, "PDF is not ready")
    geometry = json.loads(revision.page_geometry or "[]")
    if len(geometry) != revision.page_count:
        raise HTTPException(409, "PDF geometry is not ready")
    for segment in data.segments:
        if segment.page_index >= revision.page_count:
            raise HTTPException(422, "page index is outside the document")
        values = list(segment.quad_points or [])
        if segment.anchor_x is not None:
            values.append(segment.anchor_x)
        if segment.anchor_y is not None:
            values.append(segment.anchor_y)
        if any(not (-1_000_000 < value < 1_000_000) for value in values):
            raise HTTPException(422, "invalid PDF coordinates")
        left, bottom, right, top = geometry[segment.page_index]
        if segment.quad_points is not None:
            xs: Sequence[float | None] = segment.quad_points[0::2]
            ys: Sequence[float | None] = segment.quad_points[1::2]
        else:
            xs = [segment.anchor_x]
            ys = [segment.anchor_y]
        tolerance = 2.0
        if any(
            value is None or value < left - tolerance or value > right + tolerance for value in xs
        ):
            raise HTTPException(422, "annotation is outside the PDF page")
        if any(
            value is None or value < bottom - tolerance or value > top + tolerance for value in ys
        ):
            raise HTTPException(422, "annotation is outside the PDF page")


RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)$")


def ranged_file(request: Request, path: Path, etag: str, filename: str):
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "ETag": f'"{etag}"',
        "Content-Disposition": f'inline; filename="{Path(filename).name}"',
    }
    value = request.headers.get("range")
    if not value:
        return FileResponse(path, media_type="application/pdf", headers=headers)
    match = RANGE_PATTERN.fullmatch(value.strip())
    if not match:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    start_text, end_text = match.groups()
    if not start_text:
        length = int(end_text)
        start, end = max(0, size - length), size - 1
    else:
        start = int(start_text)
        end = min(int(end_text) if end_text else size - 1, size - 1)
    if start >= size or start > end:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})

    def chunks():
        with path.open("rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers.update({
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(
        chunks(), status_code=206, media_type="application/pdf", headers=headers
    )


app = create_app()
