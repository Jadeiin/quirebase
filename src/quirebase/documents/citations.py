from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.citation import (
    available_builtin_styles,
    builtin_style_xml,
    is_valid_csl,
    item_to_csl_json,
    render_bibliography,
    render_citation,
)
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.discovery.bibliography import SUPPORTED_FORMATS, export_bibliography
from quirebase.models import CitationStyle

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import User


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


def create_custom_citation_style(
    db: Session, user: User, name: str, csl: str
) -> CitationStyle:
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


def get_item_citation_response(
    db: Session, user: User, item_id: str, file_format: str, style_key: str = "apa"
) -> tuple[str, str, str]:
    item = require_readable_item(db, user, item_id)
    if file_format == "csl":
        style_xml = resolve_style_xml(db, user, style_key)
        if style_xml is None:
            raise ValidationFailure("unknown citation style")
        entries = render_bibliography([item_to_csl_json(item)], style_xml)
        return "\n\n".join(entries), "text/plain", "quirebase-citations.txt"
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, or endnote")
    contents = export_bibliography([item], file_format)
    media_type = {
        "bibtex": "application/x-bibtex",
        "ris": "application/x-research-info-systems",
        "endnote": "application/x-endnote-refer",
    }[file_format]
    extension = {"bibtex": "bib", "ris": "ris", "endnote": "enw"}[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename


def get_item_citation_text_response(
    db: Session, user: User, item_id: str, style_key: str = "apa", output: str = "text"
) -> tuple[str, str]:
    item = require_readable_item(db, user, item_id)
    style_xml = resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    rendered = render_citation(item, style_xml, output_format=output)
    media_type = "text/html" if output == "html" else "text/plain"
    return rendered, media_type
