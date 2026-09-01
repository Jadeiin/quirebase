from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse

from quirebase.core.config import get_settings
from quirebase.core.database import get_db
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.documents import (
    create_attachment as create_attachment_op,
)
from quirebase.documents import (
    create_item_document_bundle,
    delete_attachment,
    delete_file_revision,
    get_attachment_file,
    get_item_thumbnail,
    get_pdf_viewer_data,
    store_pdf_revision,
)
from quirebase.library import (
    AnnotationsWorkspace,
    Contributor,
    CustomField,
    DiscussionWorkspace,
    ExternalIdentifier,
    FilesWorkspace,
    ItemMetadata,
    JsonValue,
    MetadataWorkspace,
    OrganizeWorkspace,
    SummaryWorkspace,
    WorkspaceSection,
    add_tag_to_item,
    force_item_tag_recommendation,
    open_item_workspace,
    parse_author_list_string,
    regenerate_bibtex_key,
    remove_tag_from_item,
    rescan_pdf_doi,
    revise_item_metadata,
    search_authors_typeahead,
    set_item_tags,
    sync_metadata_from_upstream,
)
from quirebase.library import (
    add_discussion_message as add_discussion_message_op,
)
from quirebase.library import (
    create_item as create_item_op,
)
from quirebase.library import (
    delete_discussion_message as delete_discussion_message_op,
)
from quirebase.library import (
    delete_item as delete_item_op,
)
from quirebase.models import (
    AttachmentRole,
    ItemAuthor,
    LoginSession,
    User,
)
from quirebase.operations.settings import get_effective_setting, get_effective_settings_model
from quirebase.projects import (
    add_item_to_project as add_item_to_project_op,
)
from quirebase.projects import (
    remove_item_from_project as remove_item_from_project_op,
)
from quirebase.web.deps import current_login, current_user, protected_router
from quirebase.web.responses import content_disposition
from quirebase.web.templates import templates
from quirebase.web.uploads import upload_chunks

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

router = protected_router()


def _structured_people(
    last_names: list[str],
    first_names: list[str],
    corresponding_indices: list[str] | None = None,
) -> tuple[Contributor, ...]:
    corresponding = set(corresponding_indices or [])
    return tuple(
        Contributor(
            last_name=last.strip(),
            first_name=first_names[index] if index < len(first_names) else None,
            is_corresponding=str(index) in corresponding or "true" in corresponding,
        )
        for index, last in enumerate(last_names)
        if last.strip()
    )


def _people_from_text(value: str) -> tuple[Contributor, ...]:
    return tuple(
        Contributor(
            last_name=str(person.get("last_name") or ""),
            first_name=str(person["first_name"]) if person.get("first_name") else None,
            is_corresponding=bool(person.get("is_corresponding", False)),
        )
        for person in parse_author_list_string(value)
    )


def _identifiers_from_form(encoded: str) -> tuple[ExternalIdentifier, ...]:
    entries: tuple[ExternalIdentifier, ...] = ()
    if encoded.strip():
        try:
            parsed = json.loads(encoded)
        except json.JSONDecodeError as error:
            raise ValidationFailure("identifiers must be valid JSON") from error
        if not isinstance(parsed, dict):
            raise ValidationFailure("identifiers must be a JSON object")
        if not all(
            isinstance(provider, str) and isinstance(value, str)
            for provider, value in parsed.items()
        ):
            raise ValidationFailure("identifier names and values must be strings")
        entries = tuple(ExternalIdentifier(provider, value) for provider, value in parsed.items())
    return entries


def _custom_fields_from_form(encoded: str) -> tuple[CustomField, ...]:
    if not encoded.strip():
        return ()
    try:
        parsed = json.loads(encoded)
    except json.JSONDecodeError as error:
        raise ValidationFailure("custom fields must be valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValidationFailure("custom fields must be a JSON object")
    return tuple(CustomField(str(name), _json_value(value)) for name, value in parsed.items())


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return tuple(_json_value(entry) for entry in value)
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {str(key): _json_value(entry) for key, entry in value.items()}
    raise ValidationFailure("custom fields contain an unsupported value")


def _item_metadata_from_form(
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
    author_last_name: list[str] = Form(default=[], alias="author_last_name[]"),
    author_first_name: list[str] = Form(default=[], alias="author_first_name[]"),
    author_is_corr: list[str] = Form(default=[], alias="author_is_corr[]"),
    editor_last_name: list[str] = Form(default=[], alias="editor_last_name[]"),
    editor_first_name: list[str] = Form(default=[], alias="editor_first_name[]"),
    structured_editors_present: bool = Form(default=False),
) -> ItemMetadata:
    parsed_authors = (
        _structured_people(author_last_name, author_first_name, author_is_corr)
        if author_last_name
        else _people_from_text(authors)
    )
    parsed_editors = (
        _structured_people(editor_last_name, editor_first_name)
        if editor_last_name or structured_editors_present
        else _people_from_text(editors)
    )
    return ItemMetadata(
        title=title,
        abstract=abstract,
        keywords=tuple(value.strip() for value in keywords.split(";") if value.strip()),
        publication_date=publication_date,
        publication_title=publication_title,
        reference_type=reference_type,
        volume=volume,
        issue=issue,
        pages=pages,
        affiliation=affiliation,
        publisher=publisher,
        place_published=place_published,
        journal_abbreviation=journal_abbreviation,
        bibtex_key=bibtex_id,
        bibtex_type=bibtex_type,
        urls=tuple(value.strip() for value in urls.splitlines() if value.strip()),
        authors=parsed_authors,
        editors=parsed_editors,
        doi=doi,
        identifiers=_identifiers_from_form(identifiers),
        custom_fields=_custom_fields_from_form(custom_fields),
    )


def _initial_structured_people(
    links: list[ItemAuthor], include_corresponding: bool = False
) -> list[dict[str, Any]]:
    people: list[dict[str, Any]] = [
        {
            "last_name": link.author.last_name,
            "first_name": link.author.first_name or "",
        }
        for link in links
    ]
    if include_corresponding:
        for person, link in zip(people, links, strict=True):
            person["is_corresponding"] = link.is_corresponding
    return people


async def render_item_workspace(
    request: Request,
    item_id: str,
    section: str,
    user: User,
    login_session: LoginSession,
    db: AsyncSession,
):
    selected = WorkspaceSection.parse(section)
    view = await open_item_workspace(db, user, item_id, selected)
    context: dict[str, Any] = {
        "item": view.item,
        "can_edit": view.can_edit,
        "can_delete": view.can_delete,
        "revisions": view.revisions,
    }
    match view:
        case SummaryWorkspace():
            item_thumbnail = None
            with contextlib.suppress(ResourceNotFound):
                item_thumbnail = await get_item_thumbnail(db, user, item_id)
            context.update(
                revision_count=view.revision_count,
                attachment_count=view.attachment_count,
                annotation_count=view.annotation_count,
                message_count=view.message_count,
                summary_tags=view.tags,
                item_owner=view.item_owner,
                updater=view.updater,
                identifier_links=view.identifiers,
                item_thumbnail=item_thumbnail,
            )
        case MetadataWorkspace():
            context.update(
                author_links=view.authors,
                editor_links=view.editors,
                initial_authors=_initial_structured_people(
                    list(view.authors), include_corresponding=True
                ),
                initial_editors=_initial_structured_people(list(view.editors)),
            )
        case FilesWorkspace():
            context["attachments"] = view.attachments
        case OrganizeWorkspace():
            context.update(
                tags=view.tags,
                memberships=tuple(
                    (membership.project, membership.role) for membership in view.memberships
                ),
                assigned=view.assigned_project_ids,
                tag_matrix=view.tag_matrix,
            )
        case AnnotationsWorkspace():
            context["annotations"] = tuple(
                (entry.annotation, entry.revision, entry.author) for entry in view.annotations
            )
        case DiscussionWorkspace():
            context["messages"] = view.messages
    return templates.TemplateResponse(
        request,
        "item.html",
        {
            "user": user,
            "csrf": login_session.csrf_token,
            "active_page": "library",
            "item_section": selected.value,
            **context,
        },
    )


@router.post("/items")
async def create_item(
    metadata: ItemMetadata = Depends(_item_metadata_from_form),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await create_item_op(db, user, metadata)
    return RedirectResponse(f"/items/{result.item_id}", status_code=303)


@router.get("/items/{item_id}", response_class=HTMLResponse)
async def item_page(
    request: Request,
    item_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    return await render_item_workspace(request, item_id, "summary", user, login_session, db)


@router.get("/items/{item_id}/download")
async def download_item_route(
    item_id: str,
    revisions: str | None = None,
    include_annotations: bool = False,
    include_supplements: bool = False,
    timezone: str | None = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    revision_ids = [r.strip() for r in revisions.split(",") if r.strip()] if revisions else None
    bundle = await create_item_document_bundle(
        db,
        user,
        item_id,
        revision_ids=revision_ids,
        include_annotations=include_annotations,
        include_supplements=include_supplements,
        timezone=timezone,
    )
    return StreamingResponse(
        bundle.body,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition(bundle.filename)},
    )


@router.get("/items/{item_id}/{section}", response_class=HTMLResponse)
async def item_section_page(
    request: Request,
    item_id: str,
    section: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    return await render_item_workspace(request, item_id, section, user, login_session, db)


@router.post("/items/{item_id}/edit")
async def edit_item(
    item_id: str,
    version: int = Form(),
    metadata: ItemMetadata = Depends(_item_metadata_from_form),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await revise_item_metadata(db, user, item_id, version, metadata)
    return RedirectResponse(f"/items/{result.item_id}/metadata", status_code=303)


@router.post("/items/{item_id}/delete")
async def delete_item_route(
    item_id: str,
    confirm: str = Form(default=""),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    if confirm != "delete":
        raise ValidationFailure("confirm deletion to continue")
    await delete_item_op(db, user, item_id)
    return RedirectResponse("/library", status_code=303)


@router.post("/items/{item_id}/sync-metadata")
async def sync_metadata_route(
    item_id: str,
    version: int = Form(),
    provider: str = Form(),
    uid: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await sync_metadata_from_upstream(
        db,
        user,
        item_id,
        version,
        provider=provider,
        uid_value=uid,
        settings=await get_effective_settings_model(db),
    )
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/rescan-doi")
async def rescan_doi_route(
    item_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await rescan_pdf_doi(db, user, item_id)
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/update-bibtex-key")
async def update_bibtex_key_route(
    item_id: str,
    version: int = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await regenerate_bibtex_key(
        db,
        user,
        item_id,
        version,
    )
    return RedirectResponse(f"/items/{item_id}", status_code=303)


@router.post("/items/{item_id}/tags/matrix")
async def update_tag_matrix_route(
    item_id: str,
    tag_ids: list[str] = Form(default=[]),
    suggested_tags: list[str] = Form(default=[]),
    new_tags: str = Form(default=""),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    new_names = [*suggested_tags, *(line.strip() for line in new_tags.splitlines() if line.strip())]
    await set_item_tags(db, user, item_id, tag_ids, new_names=new_names)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/tag-recommendations")
async def regenerate_tag_recommendations(
    item_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await force_item_tag_recommendation(db, user, item_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.get("/api/authors/suggest")
async def suggest_authors(
    q: str = "",
    _user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    return await search_authors_typeahead(db, query=q)


@router.post("/items/{item_id}/attachments")
async def upload_attachment(
    item_id: str,
    attachment: UploadFile = File(),
    graphical_abstract: bool = Form(False),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await create_attachment_op(
        db,
        user,
        item_id,
        upload_chunks(attachment),
        attachment.filename or "",
        attachment.content_type or "application/octet-stream",
        await get_effective_setting(
            db, "max_attachment_bytes", get_settings().max_attachment_bytes
        ),
        role=AttachmentRole.graphical_abstract if graphical_abstract else None,
    )
    return RedirectResponse(
        f"/items/{item_id}/files?workflow={workflow.workflow_id}", status_code=303
    )


@router.get("/items/{item_id}/attachments/{attachment_id}")
async def download_attachment(
    item_id: str,
    attachment_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    response, original_name, media_type = await get_attachment_file(
        db, user, item_id, attachment_id
    )
    return StreamingResponse(
        response.body,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(original_name)},
    )


@router.post("/items/{item_id}/attachments/{attachment_id}/delete")
async def delete_item_attachment(
    item_id: str,
    attachment_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_attachment(db, user, item_id, attachment_id)
    return RedirectResponse(f"/items/{item_id}/files", status_code=303)


@router.post("/items/{item_id}/tags")
async def add_tag(
    item_id: str,
    name: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await add_tag_to_item(db, user, item_id, name)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/tags/{tag_id}/remove")
async def remove_tag(
    item_id: str,
    tag_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await remove_tag_from_item(db, user, item_id, tag_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/discussion")
async def add_discussion_message(
    item_id: str,
    body: str = Form(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await add_discussion_message_op(db, user, item_id, body)
    return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)


@router.post("/items/{item_id}/discussion/{message_id}/delete")
async def delete_discussion_message(
    item_id: str,
    message_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_discussion_message_op(db, user, item_id, message_id)
    return RedirectResponse(f"/items/{item_id}/discussion", status_code=303)


@router.post("/items/{item_id}/projects/{project_id}")
async def add_item_to_project(
    item_id: str,
    project_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await add_item_to_project_op(db, user, project_id, item_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/projects/{project_id}/remove")
async def remove_item_from_project(
    item_id: str,
    project_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await remove_item_from_project_op(db, user, project_id, item_id)
    return RedirectResponse(f"/items/{item_id}/organize", status_code=303)


@router.post("/items/{item_id}/pdf")
async def upload_pdf(
    item_id: str,
    pdf: UploadFile = File(),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    workflow = await store_pdf_revision(
        db,
        user,
        item_id,
        upload_chunks(pdf),
        pdf.filename or "",
        await get_effective_setting(db, "max_pdf_bytes", get_settings().max_pdf_bytes),
    )
    return RedirectResponse(
        f"/items/{item_id}/files?workflow={workflow.workflow_id}", status_code=303
    )


@router.post("/items/{item_id}/pdf/{revision_id}/delete")
async def delete_pdf_revision(
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_file_revision(db, user, item_id, revision_id)
    return RedirectResponse(f"/items/{item_id}/files", status_code=303)


@router.get("/items/{item_id}/pdf/{revision_id}", response_class=HTMLResponse)
async def pdf_viewer(
    request: Request,
    item_id: str,
    revision_id: str,
    user: User = Depends(current_user),
    login_session: LoginSession = Depends(current_login),
    db: AsyncSession = Depends(get_db),
):
    viewer_data = await get_pdf_viewer_data(db, user, item_id, revision_id)
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
