from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "src/quirebase/static"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def read_built(path: str) -> str:
    """Read a build artifact, failing with build instructions when absent."""
    file_path = STATIC / path
    if not file_path.is_file():
        pytest.fail(
            f"{path} is missing: src/quirebase/static is a build output directory. "
            "Run `bun install && bun run build` first."
        )
    return file_path.read_text(encoding="utf-8")


def test_alpine_is_bundled_locally_with_csp_compatible_build():
    package = read("package.json")
    bundle = read_built("app.js")
    base = read("src/quirebase/templates/base.html")
    assert '"@alpinejs/csp": "3.15.12"' in package
    assert (
        "<script type=\"module\" src=\"{{ url_for('static', path='/app.js') }}\"></script>" in base
    )
    assert len(bundle) > 10_000
    assert "sourceMappingURL" not in bundle
    assert "new Function" not in bundle


def test_wheel_force_includes_generated_static_assets():
    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        config = tomllib.load(pyproject)
    force_include = config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert force_include["src/quirebase/static"] == "quirebase/static"


def test_sdist_force_includes_generated_static_assets():
    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        config = tomllib.load(pyproject)
    force_include = config["tool"]["hatch"]["build"]["targets"]["sdist"]["force-include"]
    assert force_include["src/quirebase/static"] == "src/quirebase/static"


def test_asset_build_cleans_output_before_writing_files():
    build_script = read("scripts/build-assets.mjs")
    clean = 'await rm("src/quirebase/static", { recursive: true, force: true });'
    prepare_output = 'await mkdir("src/quirebase/static/vendor", { recursive: true });'

    assert clean in build_script
    assert build_script.index(clean) < build_script.index(prepare_output)


def test_enhanced_workspaces_keep_native_form_fallbacks():
    library = read("src/quirebase/templates/library.html")
    imports = read("src/quirebase/templates/import.html")
    online_search = read("src/quirebase/templates/online_search.html")
    assert 'x-data="libraryWorkspace"' in library
    assert 'method="post" action="/library/bulk' in library
    assert 'x-data="importWorkspace"' in imports
    assert 'method="post" action="/metadata/preview' in imports
    assert 'method="post" action="/bibliography/preview' in imports
    assert 'x-data="onlineSearch"' in online_search
    assert 'method="get" action="/online-search"' in online_search
    assert 'method="post" action="/metadata/preview' in online_search


def test_export_preferences_use_validated_per_user_browser_storage():
    source = read("src/quirebase/assets/app.js")
    library = read("src/quirebase/templates/library.html")
    item = read("src/quirebase/templates/item.html")
    assert "readExportPreferences" in source
    assert "storeExportPreferences" in source
    assert "window.localStorage" in source
    assert "schemaVersion: 1" in source
    assert "data-export-preferences-key" in library
    assert "data-export-preferences-key" in item
    assert "account:{{ user.id }}" in library
    assert "account:{{ user.id }}" in item


def test_export_preference_resets_and_style_search_do_not_cross_sections():
    source = read("src/quirebase/assets/app.js")
    assert 'resetExportPreferences(this.storageKey, "document")' in source
    assert 'resetExportPreferences(this.storageKey, "citation")' in source
    assert "fetchCitationStyles(this.styleQuery, 100, this.style)" in source
    assert "fetchCitationStyles(this.query, 50, this.style)" in source
    assert "this.style = this.citationStyles[0]" not in source


def test_export_preferences_recover_when_saved_citation_style_is_unavailable():
    source = read("src/quirebase/assets/app.js")
    assert "function resolveCitationStyle(styles, requestedKey)" in source
    assert "styles.some((style) => style.key === requestedKey)" in source
    assert "this.style = resolveCitationStyle(styles, this.style);" in source


def test_citation_copy_reports_request_and_clipboard_failures():
    source = read("src/quirebase/assets/app.js")
    template = read("src/quirebase/templates/item.html")
    assert "copyError: false" in source
    assert 'if (!response.ok) throw new Error("citation request failed")' in source
    assert 'succeeded = document.execCommand("copy")' in source
    assert 'if (!succeeded) throw new Error("clipboard copy failed")' in source
    assert 'x-show="copyError"' in template


def test_pdf_toolbar_exposes_navigation_search_zoom_and_download():
    template = read("src/quirebase/templates/pdf.html")
    script = read("src/quirebase/assets/pdf_viewer.js")
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
    assert 'id="annotation-detail"' in template
    assert "showAnnotation(annotation)" in script
    assert "status.textContent = node.title" not in script
    assert 'id="annotation-mark-kind"' in template
    assert 'value="underline"' in template
    assert 'class="pdf-download-options citation-panel' in template
    assert 'id="pdf-download-options-button"' in template
    assert 'id="pdf-download-current"' in template
    assert 'id="pdf-export-annotations"' in template
    assert 'x-data="itemDownload"' not in template
    assert 'href="/items/{{ item.id }}/download' not in template
    assert 'id="export-annotations"' not in template
    assert 'querySelector("#export-annotations")' not in script
    assert 'querySelector("#pdf-download-current")' in script
    assert "const exportUrl = `/documents/${itemId}/revisions/${revisionId}/export`" in script
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in script
    assert "timezone: browserTimezone()" in script
    assert "window.location.assign(`${exportUrl}?${params.toString()}`)" in script
    assert "contentUrl}/export" not in script
    assert "revision_id: revisionId" in script
    assert 'annotation.kind === "underline"' in script


def test_document_exports_send_browser_timezone():
    source = read("src/quirebase/assets/app.js")
    library = read("src/quirebase/templates/library.html")
    assert source.count("timezone: browserTimezone()") == 1
    assert "browserTimezone," in source
    assert 'name="timezone" :value="browserTimezone()"' in library


def test_password_form_aligns_frontend_validation_with_backend_policy():
    package = read("package.json")
    source = read("src/quirebase/assets/app.js")
    bundle = read_built("app.js")
    template = read("src/quirebase/templates/account_settings.html")
    assert '"@zxcvbn-ts/core": "4.2.0"' in package
    assert '"@zxcvbn-ts/language-common": "4.1.3"' in package
    assert '"@zxcvbn-ts/language-en": "4.1.1"' in package
    assert 'import("@zxcvbn-ts/core")' in source
    assert "new ZxcvbnFactory" in source
    assert "passwordStrengthAnalyzer.check(value).score" in source
    assert "--splitting" in package
    assert len(bundle) < 200_000
    assert 'import("./' in bundle
    assert template.count('minlength="12"') == 2
    assert template.count('minlength="8"') == 0
    assert 'x-data="passwordStrength"' in template
