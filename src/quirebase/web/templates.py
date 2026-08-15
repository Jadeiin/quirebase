from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from quirebase.core.i18n import (
    DEFAULT_LOCALE,
    format_date,
    format_datetime,
    format_number,
    get_translations,
    gettext,
    ngettext,
    pgettext,
    translate,
)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

# Install Jinja2 standard i18n extension
templates.env.add_extension("jinja2.ext.i18n")
templates.env.install_gettext_translations(get_translations(DEFAULT_LOCALE), newstyle=True)  # type: ignore[attr-defined]

# Register template globals and filters
templates.env.globals.update(
    locale=DEFAULT_LOCALE,
    t=translate,
    _=gettext,
    gettext=gettext,
    ngettext=ngettext,
    pgettext=pgettext,
    format_datetime=format_datetime,
    format_date=format_date,
    format_number=format_number,
)
templates.env.filters.update(
    t=translate,
    format_datetime=format_datetime,
    format_date=format_date,
    format_number=format_number,
)
