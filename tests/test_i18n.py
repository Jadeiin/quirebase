from __future__ import annotations

from pathlib import Path

from starlette.requests import Request

from quirebase.web.locale import DEFAULT_LOCALE, normalize_locale, resolve_request_locale

ROOT = Path(__file__).parents[1]


def request(*, accept_language: str = "", cookie: str = "") -> Request:
    headers = []
    if accept_language:
        headers.append((b"accept-language", accept_language.encode()))
    if cookie:
        headers.append((b"cookie", f"quirebase_locale={cookie}".encode()))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_browser_locale_negotiation_uses_supported_bcp47_tags():
    assert DEFAULT_LOCALE == "en-US"
    assert normalize_locale("zh_CN") == "zh-CN"
    assert normalize_locale("en") == "en-US"
    assert normalize_locale("unknown") == "en-US"
    assert resolve_request_locale(request(accept_language="zh-CN, en;q=0.8")) == "zh-CN"
    assert resolve_request_locale(request(accept_language="en-US, zh;q=0.8")) == "en-US"


def test_locale_cookie_has_precedence_over_accept_language():
    assert resolve_request_locale(request(accept_language="en-US", cookie="zh_CN")) == "zh-CN"


def test_lingui_catalog_is_owned_by_the_svelte_frontend():
    source = (ROOT / "frontend/src/lib/i18n.ts").read_text(encoding="utf-8")
    english = ROOT / "frontend/src/lib/locales/en-US/messages.po"
    chinese = ROOT / "frontend/src/lib/locales/zh-CN/messages.po"
    assert "@lingui/core" in source
    assert english.exists()
    assert chinese.exists()
    assert 'msgid "Library"' in chinese.read_text(encoding="utf-8")
    assert not any((ROOT / "src/quirebase/templates").glob("*"))
    assert not (ROOT / "src/quirebase/core/i18n.py").exists()
