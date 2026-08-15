from __future__ import annotations

import re
from pathlib import Path
from string import Formatter

from quirebase.core.i18n import DEFAULT_LOCALE, catalog, translate

ROOT = Path(__file__).parents[1]
TEMPLATE_DIR = ROOT / "src/quirebase/templates"
STATIC_TRANSLATION = re.compile(r"\bt\(\s*(['\"])(.*?)\1")


def fields(message: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(message) if name is not None}


def test_simplified_chinese_catalog_covers_static_template_messages():
    messages = catalog()
    used = set()
    for template in TEMPLATE_DIR.glob("*.html"):
        used.update(
            match.group(2)
            for match in STATIC_TRANSLATION.finditer(template.read_text(encoding="utf-8"))
        )
    assert used
    assert used <= messages.keys()


def test_translations_preserve_interpolation_fields():
    for source, translated in catalog().items():
        assert fields(source) == fields(translated), source


def test_default_locale_and_translation_fallback():
    assert DEFAULT_LOCALE == "zh-CN"
    assert translate("Dashboard") == "仪表盘"
    pagination = translate("Page {page} of {pages}", page=2, pages=3)
    assert pagination.startswith("第 2 页")
    assert pagination.endswith("共 3 页")
    assert translate("Dashboard", locale="en") == "Dashboard"
    assert translate("Uncatalogued product name") == "Uncatalogued product name"
