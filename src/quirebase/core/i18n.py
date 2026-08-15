from __future__ import annotations

import json
from functools import cache
from pathlib import Path

DEFAULT_LOCALE = "zh-CN"
LOCALES_DIR = Path(__file__).resolve().parent.parent / "locales"


@cache
def catalog(locale: str = DEFAULT_LOCALE) -> dict[str, str]:
    path = LOCALES_DIR / f"{locale}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def translate(message: str, /, locale: str = DEFAULT_LOCALE, **values: object) -> str:
    translated = catalog(locale).get(message, message)
    return translated.format(**values) if values else translated
