from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, override

from fastapi.templating import Jinja2Templates
from inquiro.richtext import convert_rich_text

from quirebase.core.i18n import (
    DEFAULT_LOCALE,
    bcp47_tag,
    format_date,
    format_datetime,
    format_number,
    get_translations,
    gettext,
    negotiate_locale,
    ngettext,
    normalize_locale,
    pgettext,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from fastapi import Request

PACKAGE_DIR = Path(__file__).resolve().parent.parent


def _rich_text_html(value: str | None) -> str:
    return convert_rich_text(value, source="html", target="web")


def _rich_text_plain(value: str | None) -> str:
    return convert_rich_text(value, source="html", target="text")


def resolve_request_locale(request: Request) -> str:
    # 1. Explicit user cookie preference
    cookie_loc = request.cookies.get("quirebase_locale")
    if cookie_loc:
        return normalize_locale(cookie_loc)
    # 2. Accept-Language negotiation
    accept_lang = request.headers.get("accept-language")
    if accept_lang:
        return negotiate_locale(accept_lang, default=DEFAULT_LOCALE)
    # 3. Default fallback
    return DEFAULT_LOCALE


class I18nTemplates(Jinja2Templates):
    @override
    def TemplateResponse(
        self,
        request: Request,
        name: str,
        context: dict[str, Any] | None = None,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
        media_type: str | None = None,
        background: Any = None,
    ):
        ctx: dict[str, Any] = context.copy() if context else {}
        loc = resolve_request_locale(request)
        ctx.setdefault("locale", bcp47_tag(loc))
        ctx.setdefault("active_locale", loc)
        ctx.setdefault("_", lambda msg, **k: gettext(msg, locale=loc, **k))
        ctx.setdefault("gettext", lambda msg, **k: gettext(msg, locale=loc, **k))
        ctx.setdefault("ngettext", lambda s, p, n: ngettext(s, p, n, locale=loc))
        ctx.setdefault("pgettext", lambda c, msg, **k: pgettext(c, msg, locale=loc, **k))
        ctx.setdefault(
            "format_datetime",
            lambda dt, fmt="medium": format_datetime(dt, format=fmt, locale=loc),
        )
        ctx.setdefault(
            "format_date",
            lambda d, fmt="medium": format_date(d, format=fmt, locale=loc),
        )
        ctx.setdefault("format_number", lambda num: format_number(num, locale=loc))
        return super().TemplateResponse(
            request,
            name,
            ctx,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )


templates = I18nTemplates(directory=PACKAGE_DIR / "templates")

# Install Jinja2 standard i18n extension
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_gettext_translations(get_translations(DEFAULT_LOCALE), newstyle=True)  # type: ignore[attr-defined]

# Register template globals and filters
templates.env.globals.update(
    locale=bcp47_tag(),
    _=gettext,
    gettext=gettext,
    ngettext=ngettext,
    pgettext=pgettext,
    format_datetime=format_datetime,
    format_date=format_date,
    format_number=format_number,
)
templates.env.filters.update(
    format_datetime=format_datetime,
    format_date=format_date,
    format_number=format_number,
    rich_text=_rich_text_html,
    rich_text_plain=_rich_text_plain,
)
