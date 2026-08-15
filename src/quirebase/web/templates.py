from __future__ import annotations

from pathlib import Path

from fastapi.templating import Jinja2Templates

from quirebase.core.i18n import DEFAULT_LOCALE, translate

PACKAGE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
templates.env.globals.update(locale=DEFAULT_LOCALE, t=translate)
