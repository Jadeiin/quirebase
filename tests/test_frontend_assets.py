from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_alpine_is_bundled_locally_with_csp_compatible_build():
    package = read("package.json")
    bundle = read("src/quirebase/static/app.js")
    base = read("src/quirebase/templates/base.html")
    assert '"@alpinejs/csp": "3.15.12"' in package
    assert "app.js" in base
    assert len(bundle) > 10_000
    assert "sourceMappingURL" not in bundle
    assert "new Function" not in bundle


def test_enhanced_workspaces_keep_native_form_fallbacks():
    library = read("src/quirebase/templates/library.html")
    imports = read("src/quirebase/templates/import.html")
    assert 'x-data="libraryWorkspace"' in library
    assert 'method="post" action="/library/bulk' in library
    assert 'x-data="importWorkspace"' in imports
    assert 'method="post" action="/metadata/preview' in imports
    assert 'method="post" action="/bibliography/preview' in imports


def test_pdf_toolbar_exposes_navigation_search_zoom_and_download():
    template = read("src/quirebase/templates/pdf.html")
    script = read("src/quirebase/static/pdf_viewer.js")
    for control in (
        "pdf-previous-page",
        "pdf-next-page",
        "pdf-zoom-out",
        "pdf-zoom-in",
        "pdf-search",
        "pdf-scale",
    ):
        assert f'id="{control}"' in template
        assert f"#{control}" in script
    assert "download" in template
    assert 'eventBus.dispatch("find"' in script
