from __future__ import annotations

import re
from datetime import UTC
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
    used: set[str] = set()
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


def test_babel_gettext_and_plural_support():
    from quirebase.core.i18n import gettext, ngettext, pgettext

    assert gettext("Dashboard") == "仪表盘"
    assert gettext("Nonexistent String") == "Nonexistent String"
    # Singular/plural
    assert ngettext("{n} item", "{n} items", 1) in (
        "{n} item",
        "{n} items",
        "1 个条目",
        "{n} 个条目",
    )
    # Contextual translation
    assert pgettext("Admin", "Dashboard") == "仪表盘"


def test_babel_formatting_and_locale_negotiation():
    from datetime import datetime

    from quirebase.core.i18n import (
        format_datetime,
        format_number,
        negotiate_locale,
    )

    dt = datetime(2026, 8, 15, 14, 30, tzinfo=UTC)
    formatted_dt = format_datetime(dt, locale="zh_CN")
    assert "2026" in formatted_dt

    formatted_num = format_number(1234567.89, locale="zh_CN")
    assert "1,234,567.89" in formatted_num or "1234567.89" in formatted_num

    assert negotiate_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh_CN"
    assert negotiate_locale("en-US,en;q=0.9") == "en_US"
    assert negotiate_locale("") == "zh-CN"
