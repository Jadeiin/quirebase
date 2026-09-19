from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_frontend_locale_metadata_owns_the_supported_catalogs():
    metadata = (ROOT / "frontend/src/lib/locale.ts").read_text(encoding="utf-8")
    config = (ROOT / "frontend/lingui.config.ts").read_text(encoding="utf-8")
    supported = re.search(r"SUPPORTED_LOCALES = \[([^\]]*)\]", metadata)
    default = re.search(r"DEFAULT_LOCALE: Locale = '([^']+)'", metadata)

    assert supported is not None
    assert default is not None
    locales = tuple(re.findall(r"'([^']+)'", supported.group(1)))
    assert locales == ("en-US", "zh-CN")
    assert default.group(1) == "en-US"
    assert "SUPPORTED_LOCALES" in config
    assert "DEFAULT_LOCALE" in config
    for locale in locales:
        assert (ROOT / f"frontend/src/lib/locales/{locale}/messages.po").is_file()


def test_committed_catalogs_have_no_missing_or_fuzzy_translations():
    for locale in ("en-US", "zh-CN"):
        text = (ROOT / f"frontend/src/lib/locales/{locale}/messages.po").read_text(encoding="utf-8")
        entries = re.findall(
            r'^msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"$',
            text,
            re.MULTILINE,
        )
        messages = [(msgid, msgstr) for msgid, msgstr in entries if msgid]
        assert messages
        assert [msgid for msgid, msgstr in messages if not msgstr] == []
        assert re.search(r"^#, fuzzy", text, re.MULTILINE) is None


def test_translated_catalog_does_not_leave_english_copy():
    text = (ROOT / "frontend/src/lib/locales/zh-CN/messages.po").read_text(encoding="utf-8")
    entries = re.findall(
        r'^msgid "((?:[^"\\]|\\.)*)"\nmsgstr "((?:[^"\\]|\\.)*)"$',
        text,
        re.MULTILINE,
    )
    exempt = {"CSL XML", "DOI", "OpenAPI", "PDF", "{kind} · {size} KB", "{size} MB"}
    untranslated = [
        msgid
        for msgid, msgstr in entries
        if msgid
        and msgstr
        and msgid not in exempt
        and re.search(r"[\u3400-\u9fff]", msgstr) is None
    ]
    assert untranslated == []


def test_lingui_catalog_is_owned_by_the_svelte_frontend():
    source = (ROOT / "frontend/src/lib/i18n.ts").read_text(encoding="utf-8")
    english = ROOT / "frontend/src/lib/locales/en-US/messages.po"
    chinese = ROOT / "frontend/src/lib/locales/zh-CN/messages.po"
    assert "@lingui/core" in source
    assert english.exists()
    assert chinese.exists()
    assert 'msgid "Library"' in chinese.read_text(encoding="utf-8")
