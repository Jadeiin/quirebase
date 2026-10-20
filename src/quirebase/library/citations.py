from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from inquiro.bibliography import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    DEFAULT_CITATION_KEY_FORMULA,
    SUPPORTED_FORMATS,
    BibliographyExportOptions,
    CitationKeyFormulaError,
    CitationStyleOption,
    CitationStyleSelection,
    InvalidExportOptions,
    builtin_style_xml,
    export_bibliography_records,
    is_valid_csl,
    render_bibliography,
    render_citation,
    select_builtin_citation_styles,
    work_to_csl_json,
)
from inquiro.bibliography import (
    preview_citation_key as preview_formula,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import (
    require_accessible_items,
    require_readable_item,
    visible_items_query,
)
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.models import CitationStyle, Item

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import User


class BibliographyFormat(StrEnum):
    bibtex = "bibtex"
    ris = "ris"
    csl_json = "csl-json"
    commonmeta = "commonmeta"
    csl = "csl"


@dataclass(frozen=True)
class BibliographyExport:
    content: str
    media_type: str
    filename: str


@dataclass(frozen=True)
class ItemCitation:
    content: str
    media_type: str


def preview_citation_key(formula: str, *, force_ascii: bool = False) -> str:
    if len(formula) > 1000:
        raise ValidationFailure("citation key formula is too long")
    try:
        return preview_formula(formula, force_ascii=force_ascii)
    except CitationKeyFormulaError as error:
        raise ValidationFailure(str(error)) from error


async def resolve_style_xml(
    db: AsyncSession, user: User | None, workspace_id: UUID, style_key: str
) -> str | None:
    builtin = await asyncio.to_thread(builtin_style_xml, style_key)
    if builtin:
        return builtin
    if user is None:
        return None
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    try:
        style_id = UUID(style_key)
    except ValueError:
        return None
    style = await db.scalar(
        select(CitationStyle).where(
            CitationStyle.id == style_id, CitationStyle.workspace_id == workspace_id
        )
    )
    if style is None:
        return None
    return style.csl_xml


async def list_custom_citation_styles(
    db: AsyncSession, user: User, workspace_id: UUID
) -> list[CitationStyle]:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    styles = await db.scalars(
        select(CitationStyle)
        .where(CitationStyle.workspace_id == workspace_id)
        .order_by(CitationStyle.name, CitationStyle.id)
    )
    return list(styles)


async def create_custom_citation_style(
    db: AsyncSession, user: User, workspace_id: UUID, name: str, csl: str
) -> CitationStyle:
    await require_workspace_action(db, user, workspace_id, ResourceAction.citation_style_manage)
    cleaned = name.strip()[:120]
    if not cleaned:
        raise ValidationFailure("style name is required")
    if not is_valid_csl(csl):
        raise ValidationFailure("the CSL text is not a valid citation style")
    query = select(CitationStyle.id).where(
        CitationStyle.workspace_id == workspace_id, CitationStyle.name == cleaned
    )
    if await db.scalar(query) is not None:
        raise ValidationFailure("citation style name already exists in Workspace")
    style = CitationStyle(workspace_id=workspace_id, created_by=user.id, name=cleaned, csl_xml=csl)
    try:
        async with db.begin_nested():
            db.add(style)
            await db.flush()
    except IntegrityError:
        if await db.scalar(query) is None:
            raise
        raise ValidationFailure("citation style name already exists in Workspace") from None
    await db.commit()
    return style


async def delete_custom_citation_style(
    db: AsyncSession, user: User, workspace_id: UUID, style_id: UUID
) -> None:
    await require_workspace_action(db, user, workspace_id, ResourceAction.citation_style_manage)
    style = await db.scalar(
        select(CitationStyle)
        .where(CitationStyle.workspace_id == workspace_id, CitationStyle.id == style_id)
        .with_for_update()
    )
    if style is None:
        raise ResourceNotFound("citation style not found")
    await db.delete(style)
    await db.flush()
    await db.commit()


async def _format_bibliography(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    items: list[Item],
    file_format: BibliographyFormat,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> BibliographyExport:
    if file_format != BibliographyFormat.csl:
        return _format_standard_bibliography(items, file_format, options=options)
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        options = (options or BibliographyExportOptions()).validated(file_format="csl")
        entries = render_bibliography(
            [
                work_to_csl_json(
                    item.work,
                    options,
                    item_id=str(item.id),
                )
                for item in items
            ],
            style_xml,
        )
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    return BibliographyExport("\n\n".join(entries), "text/plain", "quirebase-citations.txt")


def _format_standard_bibliography(
    items: list[Item],
    file_format: BibliographyFormat,
    options: BibliographyExportOptions | None = None,
) -> BibliographyExport:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, csl-json, or commonmeta")
    try:
        contents = export_bibliography_records(
            [item.work for item in items],
            file_format,
            options=options,
            citation_keys=[item.citation_key for item in items],
        )
    except (InvalidExportOptions, CitationKeyFormulaError, ValueError) as error:
        raise ValidationFailure(str(error)) from error
    media_type = BIBLIOGRAPHY_MEDIA_TYPES[file_format]
    extension = BIBLIOGRAPHY_EXTENSIONS[file_format]
    filename = f"quirebase-export.{extension}"
    return BibliographyExport(contents, media_type, filename)


async def export_item_bibliography(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    file_format: BibliographyFormat,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> BibliographyExport:
    item = await require_readable_item(db, user, workspace_id, item_id)
    return await _format_bibliography(
        db, user, workspace_id, [item], file_format, style_key=style_key, options=options
    )


async def export_selected_bibliography(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_ids: list[UUID],
    file_format: BibliographyFormat,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> BibliographyExport:
    items = await require_accessible_items(db, user, workspace_id, item_ids)
    return await _format_bibliography(
        db, user, workspace_id, items, file_format, style_key=style_key, options=options
    )


async def export_workspace_bibliography(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    file_format: BibliographyFormat,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> BibliographyExport:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_export)
    items = list(
        await db.scalars(
            visible_items_query(workspace_id).order_by(Item.updated_at.desc(), Item.id)
        )
    )
    return await _format_bibliography(
        db, user, workspace_id, items, file_format, style_key=style_key, options=options
    )


async def render_item_citation(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    style_key: str = "apa",
    output: Literal["text", "html"] = "text",
) -> ItemCitation:
    item = await require_readable_item(db, user, workspace_id, item_id)
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        rendered = render_citation(item.work, style_xml, output_format=output)
    except ValueError as error:
        raise ValidationFailure(str(error)) from error
    media_type = "text/html" if output == "html" else "text/plain"
    return ItemCitation(rendered, media_type)


__all__ = [
    "BIBLIOGRAPHY_EXTENSIONS",
    "BIBLIOGRAPHY_MEDIA_TYPES",
    "DEFAULT_CITATION_KEY_FORMULA",
    "BibliographyExport",
    "BibliographyExportOptions",
    "BibliographyFormat",
    "CitationStyleOption",
    "CitationStyleSelection",
    "ItemCitation",
    "create_custom_citation_style",
    "delete_custom_citation_style",
    "export_item_bibliography",
    "export_selected_bibliography",
    "export_workspace_bibliography",
    "list_custom_citation_styles",
    "preview_citation_key",
    "render_item_citation",
    "resolve_style_xml",
    "select_builtin_citation_styles",
]
