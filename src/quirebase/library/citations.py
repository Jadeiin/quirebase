from __future__ import annotations

from typing import TYPE_CHECKING

from inquiro.bibliography import SUPPORTED_FORMATS, export_bibliography
from inquiro.citations import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    CitationEngineUnavailable,
    CitationStyleOption,
    CitationStyleSelection,
    ExportOptions,
    _builtin_style_catalog,
    builtin_style_xml,
    is_valid_csl,
    item_to_csl_json,
    render_bibliography,
    render_citation,
)
from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.models import CitationStyle

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import Item, User


def select_builtin_citation_styles(
    query: str = "", limit: int = 50, include: str = ""
) -> CitationStyleSelection:
    catalog = _builtin_style_catalog()
    normalized_query = query.strip().casefold()
    matches = (
        option
        for option in catalog
        if not normalized_query
        or normalized_query in option.key.casefold()
        or normalized_query in option.name.casefold()
    )
    styles = tuple(list(matches)[: max(1, min(limit, 200))])
    normalized_include = include.strip().casefold()
    included = next(
        (
            option
            for option in catalog
            if normalized_include and option.key.casefold() == normalized_include
        ),
        None,
    )
    if included is not None and any(option.key == included.key for option in styles):
        included = None
    return CitationStyleSelection(matches=styles, included=included)


def resolve_style_xml(db: Session, user: User | None, style_key: str) -> str | None:
    builtin = builtin_style_xml(style_key)
    if builtin:
        return builtin
    if user is None:
        return None
    style = db.get(CitationStyle, style_key)
    if style is None or style.created_by != user.id:
        return None
    return style.csl_xml


def list_custom_citation_styles(db: Session, user: User) -> list[CitationStyle]:
    return list(
        db.scalars(
            select(CitationStyle)
            .where(CitationStyle.created_by == user.id)
            .order_by(CitationStyle.name)
        ).all()
    )


def create_custom_citation_style(db: Session, user: User, name: str, csl: str) -> CitationStyle:
    name = name.strip()
    if not name:
        raise ValidationFailure("style name is required")
    if len(name) > 120:
        name = name[:120]
    if not is_valid_csl(csl):
        raise ValidationFailure("the CSL text is not a valid citation style")
    style = CitationStyle(name=name, csl_xml=csl, created_by=user.id)
    db.add(style)
    db.commit()
    return style


def delete_custom_citation_style(db: Session, user: User, style_id: str) -> None:
    style = db.get(CitationStyle, style_id)
    if style is None or style.created_by != user.id:
        raise ResourceNotFound("citation style not found")
    db.delete(style)
    db.commit()


def format_csl_export(
    db: Session,
    user: User,
    items: list[Item],
    style_key: str = "apa",
    options: ExportOptions | None = None,
) -> tuple[str, str, str]:
    style_xml = resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        entries = render_bibliography(
            [item_to_csl_json(item, options=options) for item in items], style_xml
        )
    except CitationEngineUnavailable as error:
        raise ValidationFailure(str(error)) from error
    return "\n\n".join(entries), "text/plain", "quirebase-citations.txt"


def format_standard_export(
    items: list[Item], file_format: str, options: ExportOptions | None = None
) -> tuple[str, str, str]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, or endnote")
    options = options or ExportOptions()
    contents = export_bibliography(
        items,
        file_format,
        include_abstract=options.include_abstract,
        preserve_case=options.preserve_case,
        abbreviate_journal=options.abbreviate_journal,
        include_identifiers=options.include_identifiers,
        include_custom_fields=options.include_custom_fields,
    )
    media_type = BIBLIOGRAPHY_MEDIA_TYPES[file_format]
    extension = BIBLIOGRAPHY_EXTENSIONS[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename


def get_item_citation_response(
    db: Session,
    user: User,
    item_id: str,
    file_format: str,
    style_key: str = "apa",
    options: ExportOptions | None = None,
) -> tuple[str, str, str]:
    item = require_readable_item(db, user, item_id)
    if file_format == "csl":
        return format_csl_export(db, user, [item], style_key=style_key, options=options)
    return format_standard_export([item], file_format, options=options)


def get_item_citation_text_response(
    db: Session, user: User, item_id: str, style_key: str = "apa", output: str = "text"
) -> tuple[str, str]:
    item = require_readable_item(db, user, item_id)
    style_xml = resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        rendered = render_citation(item, style_xml, output_format=output)
    except CitationEngineUnavailable as error:
        raise ValidationFailure(str(error)) from error
    media_type = "text/html" if output == "html" else "text/plain"
    return rendered, media_type


__all__ = [
    "BIBLIOGRAPHY_EXTENSIONS",
    "BIBLIOGRAPHY_MEDIA_TYPES",
    "CitationStyleOption",
    "CitationStyleSelection",
    "ExportOptions",
    "create_custom_citation_style",
    "delete_custom_citation_style",
    "format_csl_export",
    "format_standard_export",
    "get_item_citation_response",
    "get_item_citation_text_response",
    "list_custom_citation_styles",
    "resolve_style_xml",
    "select_builtin_citation_styles",
]
