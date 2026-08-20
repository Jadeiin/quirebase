from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path
from string import Formatter

from babel.messages.pofile import read_po

from quirebase.core.i18n import (
    DEFAULT_LOCALE,
    _,
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

ROOT = Path(__file__).parents[1]
PO_PATH = ROOT / "src/quirebase/locales/zh_CN/LC_MESSAGES/messages.po"
TEMPLATE_DIR = ROOT / "src/quirebase/templates"
STATIC_TRANSLATION = re.compile(r"\b_\s*\(\s*(['\"])(.*?)\1")


def fields(message: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(message) if name is not None}


def _translation_entries() -> dict[str, str]:
    """Flatten catalog msgids (including plural tuple ids) to their msgstr."""
    with PO_PATH.open("r", encoding="utf-8") as f:
        catalog = read_po(f)
    entries: dict[str, str] = {}
    for message in catalog:
        if not message.id:
            continue
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        strings = message.string if isinstance(message.string, tuple) else (message.string,)
        for mid in ids:
            if isinstance(mid, str):
                entries[mid] = next((s for s in strings if s), "")
    return entries


def test_simplified_chinese_catalog_covers_static_template_messages():
    translations = _translation_entries()
    used: set[str] = set()
    for template in TEMPLATE_DIR.glob("*.html"):
        used.update(
            match.group(2)
            for match in STATIC_TRANSLATION.finditer(template.read_text(encoding="utf-8"))
        )
    assert used, "no translatable strings found in templates"
    missing = used - set(translations)
    assert not missing, f"templates use messages missing from catalog: {sorted(missing)}"
    untranslated = {m for m in used if not translations[m]}
    assert not untranslated, f"catalog entries without translation: {sorted(untranslated)}"


def test_po_catalog_coverage_and_interpolation_fields():
    assert PO_PATH.exists(), f"PO file does not exist at {PO_PATH}"
    with PO_PATH.open("r", encoding="utf-8") as f:
        po_catalog = read_po(f)

    assert len(po_catalog) > 0, "PO catalog should not be empty"

    for message in po_catalog:
        if not message.id:
            continue
        if isinstance(message.id, str) and message.string:
            # If there are format fields in msgid, ensure msgstr preserves them
            src_fields = fields(message.id)
            if src_fields:
                trans_fields = fields(message.string)
                assert src_fields == trans_fields, (
                    f"Field mismatch in msgid {message.id!r}: expected {src_fields}, got {trans_fields}"
                )


def test_default_locale_and_translation_lookup():
    assert DEFAULT_LOCALE == "en_US"
    assert gettext("Dashboard") == "Dashboard"
    assert gettext("Dashboard", locale="zh_CN") == "仪表盘"
    assert _("Dashboard", locale="zh_CN") == "仪表盘"
    assert _("Administration", locale="zh_CN") == "管理"
    assert gettext("Dashboard", locale="en_US") == "Dashboard"
    assert gettext("Uncatalogued product name") == "Uncatalogued product name"


def test_babel_gettext_and_plural_and_contextual():
    assert gettext("Dashboard", locale="zh_CN") == "仪表盘"
    assert gettext("Nonexistent String") == "Nonexistent String"
    # Singular/plural
    plural_res = ngettext("{n} item", "{n} items", 1, locale="zh_CN")
    assert plural_res in ("{n} item", "{n} items", "1 个条目", "{n} 个条目")
    # Contextual translation
    assert pgettext("Admin", "Dashboard", locale="zh_CN") == "仪表盘"


def test_babel_formatting_and_locale_negotiation():
    dt = datetime(2026, 8, 15, 14, 30, tzinfo=UTC)
    formatted_dt = format_datetime(dt, locale="zh_CN")
    assert "2026" in formatted_dt

    d = date(2026, 8, 15)
    formatted_d = format_date(d, locale="zh_CN")
    assert "2026" in formatted_d

    formatted_num = format_number(1234567.89, locale="zh_CN")
    assert "1,234,567.89" in formatted_num or "1234567.89" in formatted_num

    assert negotiate_locale("zh-CN,zh;q=0.9,en;q=0.8") == "zh_CN"
    assert negotiate_locale("en-US,en;q=0.9") == "en_US"
    assert negotiate_locale("") == "en_US"


def test_normalize_locale():
    assert normalize_locale("zh-CN") == "zh_CN"
    assert normalize_locale("zh_CN") == "zh_CN"
    assert normalize_locale("en-US") == "en_US"
    assert normalize_locale("en") == "en"
    assert normalize_locale("") == "en_US"


def test_get_translations_caching():
    trans1 = get_translations("zh_CN")
    trans2 = get_translations("zh_CN")
    assert trans1 is trans2
