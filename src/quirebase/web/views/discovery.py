from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.discovery import (
    MetadataLookupError,
    SearchClause,
    commit_import_batch,
    export_accessible_bibliography,
    get_user_imported_identifiers,
    record_search_audit,
    search_metadata,
    stage_import_batch,
    stage_metadata_batch,
)
from quirebase.discovery import (
    import_published_pdf as import_published_pdf_op,
)
from quirebase.discovery import (
    import_unpublished_pdf as import_unpublished_pdf_op,
)
from quirebase.models import (
    LoginSession,
    User,
)
from quirebase.web.deps import current_login, current_user, require_csrf
from quirebase.web.templates import templates

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()


@router.get("/bibliography/import", response_class=HTMLResponse)
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


@router.get("/online-search", response_class=HTMLResponse)
def online_search_page(
    request: Request,
    provider: str = "openalex",
    sort: str = "relevance",
    year_from: str = "",
    year_to: str = "",
    page: int = 1,
    user: User = Depends(current_user),
    login: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    fields = request.query_params.getlist("field")
    operators = request.query_params.getlist("operator")
    terms = request.query_params.getlist("term")
    clauses = [
        SearchClause(field, operator, term.strip())
        for field, operator, term in zip(fields, operators, terms, strict=False)
        if term.strip()
    ]
    defaults = ("any", "title", "author", "publication", "abstract")
    while len(fields) < 5:
        fields.append(defaults[len(fields)])
    while len(operators) < 5:
        operators.append("and")
    while len(terms) < 5:
        terms.append("")
    visible_clause_count = max(
        1,
        max((index + 1 for index, term in enumerate(terms[:5]) if term.strip()), default=1),
    )
    results = None
    error = None
    if clauses:
        try:
            start_year = int(year_from) if year_from else None
            end_year = int(year_to) if year_to else None
            if start_year and not 1000 <= start_year <= 3000:
                raise ValueError("starting year is invalid")
            if end_year and not 1000 <= end_year <= 3000:
                raise ValueError("ending year is invalid")
            results = search_metadata(
                provider,
                clauses,
                page=page,
                per_page=10,
                sort=sort,
                year_from=start_year,
                year_to=end_year,
            )
            record_search_audit(db, user, provider, clauses, len(results.results))
        except ValueError as caught:
            error = str(caught)
        except MetadataLookupError as caught:
            error = str(caught)
    imported = get_user_imported_identifiers(db, user)
    query_items = [
        (key, value) for key, value in request.query_params.multi_items() if key != "page"
    ]

    def page_url(number: int) -> str:
        return "/online-search?" + urlencode([*query_items, ("page", number)])

    return templates.TemplateResponse(
        request,
        "online_search.html",
        {
            "user": user,
            "csrf": login.csrf_token,
            "active_page": "online_search",
            "provider": provider,
            "sort": sort,
            "year_from": year_from,
            "year_to": year_to,
            "fields": fields[:5],
            "operators": operators[:5],
            "terms": terms[:5],
            "visible_clause_count": visible_clause_count,
            "results": results,
            "error": error,
            "imported": imported,
            "page_url": page_url,
            "has_nasa_ads": bool(get_settings().nasa_ads_token),
            "has_ieee": bool(get_settings().ieee_api_key),
        },
    )


@router.post("/imports/pdf/published", dependencies=[Depends(require_csrf)])
def import_published_pdf(
    doi: str = Form(default=""),
    pdf: UploadFile = File(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    item = import_published_pdf_op(db, user, pdf.file, pdf.filename or "", doi=doi)
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.post("/imports/pdf/unpublished", dependencies=[Depends(require_csrf)])
def import_unpublished_pdf(
    title: str = Form(),
    authors: str = Form(default=""),
    abstract: str = Form(default=""),
    keywords: str = Form(default=""),
    pdf: UploadFile = File(),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    item = import_unpublished_pdf_op(
        db,
        user,
        pdf.file,
        pdf.filename or "",
        title=title,
        authors=authors,
        abstract=abstract,
        keywords=keywords,
    )
    return RedirectResponse(f"/items/{item.id}", status_code=303)


@router.post("/bibliography/preview", dependencies=[Depends(require_csrf)])
def preview_import(
    request: Request,
    bibliography: UploadFile = File(),
    file_format: str = Form(),
    user: User = Depends(current_user),
    login: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    raw = bibliography.file.read(5 * 1024 * 1024 + 1)
    batch, records, errors = stage_import_batch(db, user, raw, file_format)
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


@router.post("/metadata/preview", dependencies=[Depends(require_csrf)])
def preview_online_metadata(
    request: Request,
    identifier: str = Form(),
    provider: str = Form(default="auto"),
    user: User = Depends(current_user),
    login: LoginSession = Depends(current_login),
    db: Session = Depends(get_db),
):
    batch, records, errors = stage_metadata_batch(db, user, identifier, provider)
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


@router.post("/bibliography/import/{batch_id}", dependencies=[Depends(require_csrf)])
def commit_import(
    batch_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    commit_import_batch(db, user, batch_id)
    return RedirectResponse("/", status_code=303)


@router.get("/bibliography/export")
def export_items(
    file_format: str,
    style: str = "apa",
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    contents, media_type, filename = export_accessible_bibliography(
        db, user, file_format, style_key=style
    )
    return Response(
        contents,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
