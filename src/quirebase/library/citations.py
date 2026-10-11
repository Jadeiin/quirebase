from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from uuid import UUID

from inquiro.bibliography import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    DEFAULT_CITATION_KEY_FORMULA,
    SUPPORTED_FORMATS,
    BibliographyExportOptions,
    BibliographyRecord,
    CitationKeyFormulaError,
    CitationStyleOption,
    CitationStyleSelection,
    InvalidExportOptions,
    builtin_style_xml,
    export_bibliography_records,
    is_valid_csl,
    record_to_csl_json,
    render_bibliography,
    render_citation,
    select_builtin_citation_styles,
)
from inquiro.bibliography import (
    preview_citation_key as preview_formula,
)
from inquiro.metadata import metadata_bibliography_record
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.models import CitationStyle

from ._metadata import metadata_from_item

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import Item, ItemIdentifier, User


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


async def format_csl_export(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    items: list[Item],
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    entries = render_bibliography(
        [
            record_to_csl_json(
                _item_to_bibliography_record(item, item.identifier_links),
                options,
                item_id=str(item.id),
            )
            for item in items
        ],
        style_xml,
    )
    return "\n\n".join(entries), "text/plain", "quirebase-citations.txt"


def format_standard_export(
    items: list[Item], file_format: str, options: BibliographyExportOptions | None = None
) -> tuple[str, str, str]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, biblatex, ris, or endnote")
    try:
        contents = export_bibliography_records(
            [_item_to_bibliography_record(item, item.identifier_links) for item in items],
            file_format,
            options=options,
        )
    except (InvalidExportOptions, CitationKeyFormulaError, ValueError) as error:
        raise ValidationFailure(str(error)) from error
    media_type = BIBLIOGRAPHY_MEDIA_TYPES[file_format]
    extension = BIBLIOGRAPHY_EXTENSIONS[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename


async def get_item_citation_response(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    file_format: str,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    item = await require_readable_item(db, user, workspace_id, item_id)
    if file_format == "csl":
        return await format_csl_export(
            db, user, workspace_id, [item], style_key=style_key, options=options
        )
    return format_standard_export([item], file_format, options=options)


async def get_item_citation_text_response(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    style_key: str = "apa",
    output: str = "text",
) -> tuple[str, str]:
    item = await require_readable_item(db, user, workspace_id, item_id)
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    rendered = render_citation(
        _item_to_bibliography_record(item, item.identifier_links), style_xml, output_format=output
    )
    media_type = "text/html" if output == "html" else "text/plain"
    return rendered, media_type


__all__ = [
    "BIBLIOGRAPHY_EXTENSIONS",
    "BIBLIOGRAPHY_MEDIA_TYPES",
    "DEFAULT_CITATION_KEY_FORMULA",
    "BibliographyExportOptions",
    "CitationStyleOption",
    "CitationStyleSelection",
    "create_custom_citation_style",
    "delete_custom_citation_style",
    "format_csl_export",
    "format_standard_export",
    "get_item_citation_response",
    "get_item_citation_text_response",
    "list_custom_citation_styles",
    "preview_citation_key",
    "resolve_style_xml",
    "select_builtin_citation_styles",
]


def _item_to_bibliography_record(
    item: Item, identifiers: Sequence[ItemIdentifier]
) -> BibliographyRecord:
    return metadata_bibliography_record(metadata_from_item(item, identifiers))
