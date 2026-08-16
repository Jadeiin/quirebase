from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.discovery import (
    available_builtin_styles,
    list_custom_citation_styles,
)
from quirebase.documents import (
    create_attachment as create_attachment_op,
)
from quirebase.documents import (
    get_attachment_file,
    get_pdf_viewer_data,
    store_pdf_revision,
)
from quirebase.library import (
    add_discussion_message as add_discussion_message_op,
)
from quirebase.library import (
    add_tag_to_item,
    batch_add_tags_to_item,
    generate_bibtex_key,
    get_item_workspace_data,
    parse_author_name,
    remove_tag_from_item,
    rescan_pdf_doi,
    search_authors_typeahead,
    set_item_authors,
    set_item_tags,
    sync_metadata_from_upstream,
)
from quirebase.library import (
    create_item as create_item_op,
)
from quirebase.library import (
    delete_discussion_message as delete_discussion_message_op,
)
from quirebase.library import (
    update_item as update_item_op,
)
from quirebase.models import (
    LoginSession,
    User,
)
from quirebase.operations.settings import get_effective_setting
from quirebase.projects import (
    add_item_to_project as add_item_to_project_op,
)
from quirebase.projects import (
    remove_item_from_project as remove_item_from_project_op,
)
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


def render_item_workspace(
    request: Request,
    item_id: str,
    section: str,
    user: User,
    login_session: LoginSession,
    db: Session,
):
    data = get_item_workspace_data(db, user, item_id, section)
    return templates.TemplateResponse(
        request,
        "item.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "active_page": "library",
            "item_section": section,
            "builtin_styles": available_builtin_styles(),
            "custom_styles": list_custom_citation_styles(db, user),
            **data,
        },
    )


@router.post("/items", dependencies=[Depends(require_csrf)])
def create_item(
    title: str = Form(),
    abstract: str = Form(default=""),
    authors: str = Form(default=""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    item = create_item_op(db, user, title=title, abstract=abstract, authors=authors)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
def item_page(
    request: Request,
    item_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    return render_item_workspace(request, item_id, "summary", user, login_session, db)


@router.get("/items/{item_id}/{section}", response_class=HTMLResponse)
def item_section_page(
    request: Request,
    item_id: str,
    section: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    return render_item_workspace(request, item_id, section, user, login_session, db)


@router.post("/items/{item_id}/edit", dependencies=[Depends(require_csrf)])
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
    volume: str = Form(default=""),
    issue: str = Form(default=""),
    pages: str = Form(default=""),
    affiliation: str = Form(default=""),
    publisher: str = Form(default=""),
    place_published: str = Form(default=""),
    journal_abbreviation: str = Form(default=""),
    bibtex_id: str = Form(default=""),
    bibtex_type: str = Form(default=""),
    urls: str = Form(default=""),
    identifiers: str = Form(default=""),
    custom_fields: str = Form(default=""),
    author_last_name: list[str] = Form(default=[]),
    author_first_name: list[str] = Form(default=[]),
    author_is_corr: list[str] = Form(default=[]),
    editor_last_name: list[str] = Form(default=[]),
    editor_first_name: list[str] = Form(default=[]),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    item = update_item_op(
        db,
        user,
        item_id=item_id,
        version=version,
        title=title,
        abstract=abstract,
        authors=authors,
        editors=editors,
        keywords=keywords,
        publication_date=publication_date,
        publication_title=publication_title,
        doi=doi,
        reference_type=reference_type,
        volume=volume,
        issue=issue,
        pages=pages,
        affiliation=affiliation,
        publisher=publisher,
        place_published=place_published,
        journal_abbreviation=journal_abbreviation,
        bibtex_id=bibtex_id,
        bibtex_type=bibtex_type,
        urls=urls,
        identifiers=identifiers,
        custom_fields=custom_fields,
    )
    if author_last_name:
        authors_data = []
        for idx, last in enumerate(author_last_name):
            if last.strip():
                first = author_first_name[idx] if idx < len(author_first_name) else None
                is_corr = str(idx) in author_is_corr or "true" in author_is_corr
                authors_data.append({
                    "last_name": last.strip(),
                    "first_name": first,
                    "is_corresponding": is_corr,
                })
        if authors_data or (
            not any(name.strip() for name in author_last_name) and not authors.strip()
        ):
            set_item_authors(db, user, item.id, authors_data, role="author")
    elif authors.strip():
        parsed_authors = []
        for a_str in authors.split(";"):
            if a_str.strip():
                l, f = parse_author_name(a_str.strip())
                parsed_authors.append({"last_name": l, "first_name": f})
        if parsed_authors:
            set_item_authors(db, user, item.id, parsed_authors, role="author")

    if editor_last_name:
        editors_data = []
        for idx, last in enumerate(editor_last_name):
            if last.strip():
                first = editor_first_name[idx] if idx < len(editor_first_name) else None
                editors_data.append({"last_name": last.strip(), "first_name": first})
        if editors_data or (
            not any(name.strip() for name in editor_last_name) and not editors.strip()
        ):
            set_item_authors(db, user, item.id, editors_data, role="editor")
    elif editors.strip():
        parsed_editors = []
        for e_str in editors.split(";"):
            if e_str.strip():
                l, f = parse_author_name(e_str.strip())
                parsed_editors.append({"last_name": l, "first_name": f})
        if parsed_editors:
            set_item_authors(db, user, item.id, parsed_editors, role="editor")

    return RedirectResponse(f"/items/{item.id}/metadata", status_code=303)


@router.post("/items/{item_id}/sync-metadata", dependencies=[Depends(require_csrf)])
def sync_metadata_route(
    item_id: str,
    provider: str = Form(),
    uid: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    sync_metadata_from_upstream(db, user, item_id, provider=provider, uid_value=uid)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/rescan-doi", dependencies=[Depends(require_csrf)])
def rescan_doi_route(
    item_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    rescan_pdf_doi(db, user, item_id)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/update-bibtex-key", dependencies=[Depends(require_csrf)])
def update_bibtex_key_route(
    item_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    data = get_item_workspace_data(db, user, item_id, "summary")
    item = data["item"]
    key = generate_bibtex_key(item)
    update_item_op(
        db,
        user,
        item_id=item_id,
        version=item.version,
        title=item.title,
        bibtex_id=key,
    )
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/tags/matrix", dependencies=[Depends(require_csrf)])
def update_tag_matrix_route(
    item_id: str,
    tag_ids: list[str] = Form(default=[]),
    new_tags: str = Form(default=""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    all_selected = list(tag_ids)
    if new_tags.strip():
        lines = [line.strip() for line in new_tags.splitlines() if line.strip()]
        if lines:
            created = batch_add_tags_to_item(db, user, item_id, lines)
            for t in created:
                if t.id not in all_selected:
                    all_selected.append(t.id)
    set_item_tags(db, user, item_id, all_selected)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.get("/api/authors/suggest")
def suggest_authors(
    q: str = "",
    db: Session = Depends(get_db),
):
    return search_authors_typeahead(db, query=q)


@router.post("/items/{item_id}/attachments", dependencies=[Depends(require_csrf)])
def upload_attachment(
    item_id: str,
    attachment: UploadFile = File(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    create_attachment_op(
        db,
        user,
        item_id,
        attachment.file,
        attachment.filename or "",
        attachment.content_type or "application/octet-stream",
        get_effective_setting(db, "max_attachment_bytes", get_settings().max_attachment_bytes),
    )
    return RedirectResponse(f"/items/{item_id}/files", status_code=303)


@router.get("/items/{item_id}/attachments/{attachment_id}")
def download_attachment(
    item_id: str,
    attachment_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    path, original_name, media_type = get_attachment_file(db, user, item_id, attachment_id)
    return FileResponse(
        path,
        media_type=media_type,
        filename=original_name,
        content_disposition_type="attachment",
    )


@router.post("/items/{item_id}/tags", dependencies=[Depends(require_csrf)])
def add_tag(
    item_id: str,
    name: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    add_tag_to_item(db, user, item_id, name)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/tags/{tag_id}/remove", dependencies=[Depends(require_csrf)])
def remove_tag(
    item_id: str,
    tag_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    remove_tag_from_item(db, user, item_id, tag_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/discussion", dependencies=[Depends(require_csrf)])
def add_discussion_message(
    item_id: str,
    body: str = Form(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    add_discussion_message_op(db, user, item_id, body)
    return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)


@router.post(
    "/items/{item_id}/discussion/{message_id}/delete", dependencies=[Depends(require_csrf)]
)
def delete_discussion_message(
    item_id: str,
    message_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    delete_discussion_message_op(db, user, item_id, message_id)
    return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)


@router.post("/items/{item_id}/projects/{project_id}", dependencies=[Depends(require_csrf)])
def add_item_to_project(
    item_id: str,
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    add_item_to_project_op(db, user, project_id, item_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/projects/{project_id}/remove", dependencies=[Depends(require_csrf)])
def remove_item_from_project(
    item_id: str,
    project_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    remove_item_from_project_op(db, user, project_id, item_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/pdf", dependencies=[Depends(require_csrf)])
def upload_pdf(
    item_id: str,
    pdf: UploadFile = File(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    store_pdf_revision(
        db,
        user,
        item_id,
        pdf.file,
        pdf.filename or "",
        get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes),
    )
    return RedirectResponse(f"/items/{item_id}/files", status_code=303)


@router.get("/items/{item_id}/pdf/{revision_id}", response_class=HTMLResponse)
def pdf_viewer(
    request: Request,
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    viewer_data = get_pdf_viewer_data(db, user, item_id, revision_id)
    return templates.TemplateResponse(
        request,
        "pdf.html",
        {
            "user": user,
            "item": viewer_data["item"],
            "revision": viewer_data["revision"],
            "csrf": login_session.csrf_token,
            "projects": viewer_data["projects"],
            "active_page": "library",
        },
    )
