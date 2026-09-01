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


def test_wheel_includes_generated_static_assets_as_optional_artifacts():
    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        config = tomllib.load(pyproject)
    wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert wheel["artifacts"] == ["src/quirebase/static"]
    assert "src/quirebase/static" not in wheel["force-include"]


def test_sdist_includes_generated_static_assets_as_optional_artifacts():
    with (ROOT / "pyproject.toml").open("rb") as pyproject:
        config = tomllib.load(pyproject)
    sdist = config["tool"]["hatch"]["build"]["targets"]["sdist"]
    assert sdist["artifacts"] == ["src/quirebase/static"]


def test_asset_build_cleans_output_before_writing_files():
    build_script = read("scripts/build-assets.mjs")
    clean = 'await rm("src/quirebase/static", { recursive: true, force: true });'
    prepare_output = 'await mkdir("src/quirebase/static/vendor", { recursive: true });'

    assert clean in build_script
    assert build_script.index(clean) < build_script.index(prepare_output)


def test_enhanced_workspaces_keep_native_form_fallbacks():
    app_source = read("src/quirebase/assets/app.js")
    library = read("src/quirebase/templates/library.html")
    imports = read("src/quirebase/templates/import.html")
    online_search = read("src/quirebase/templates/online_search.html")
    assert 'x-data="libraryWorkspace"' in library
    assert 'method="post" action="/library/bulk' in library
    assert 'x-data="importWorkspace"' in imports
    assert 'name="pdfs" accept="application/pdf,.pdf" multiple required' in imports
    assert '@change="addPdfFiles"' in imports
    assert "new DataTransfer()" in app_source
    assert 'method="post" action="/metadata/preview' in imports
    assert 'method="post" action="/bibliography/preview' in imports
    assert 'x-data="onlineSearch"' in online_search
    assert 'method="get" action="/online-search"' in online_search
    assert 'method="post" action="/metadata/preview' in online_search


def test_remote_pdf_is_downloaded_in_the_browser_and_reuses_the_upload_route():
    source = read("src/quirebase/assets/app.js")
    item = read("src/quirebase/templates/item.html")
    styles = read("src/quirebase/assets/styles.css")

    assert 'Alpine.data("remotePdfUpload"' in source
    assert "const download = await fetch(this.url);" in source
    assert 'form.append("pdf", new File(' in source
    assert 'csrfFetch(this.$root.action, { method: "POST", body: form })' in source
    assert 'x-data="remotePdfUpload"' in item
    assert '@submit.prevent="downloadAndUpload"' in item
    assert 'action="/items/{{ item.id }}/pdf"' in item
    assert 'class="upload-form remote-pdf-upload"' in item
    assert ".remote-pdf-upload > button { grid-column: 2; grid-row: 1; }" in styles


def test_remote_attachment_can_optionally_be_used_as_graphical_abstract():
    source = read("src/quirebase/assets/app.js")
    item = read("src/quirebase/templates/item.html")
    styles = read("src/quirebase/assets/styles.css")

    assert 'Alpine.data("remoteAttachmentUpload"' in source
    assert "if (this.graphicalAbstract)" in source
    assert 'form.append("graphical_abstract", "true")' in source
    assert '"attachment",\n        new File([blob]' in source
    assert 'x-data="remoteAttachmentUpload"' in item
    assert 'action="/items/{{ item.id }}/attachments"' in item
    assert item.count('name="graphical_abstract" value="true"') == 2
    assert item.count('class="upload-actions"') == 2
    assert "Add attachment from URL" in item
    assert "Add Graphical Abstract from URL" not in item
    assert (
        ".upload-actions { display: flex; align-items: center; justify-content: flex-end;" in styles
    )


def test_tag_suggestions_and_merge_keep_native_form_contracts():
    source = read("src/quirebase/assets/app.js")
    item = read("src/quirebase/templates/item.html")
    tools = read("src/quirebase/templates/tools.html")
    assert 'name="suggested_tags"' in item
    assert 'action="/items/{{ item.id }}/tags/matrix' in item
    assert 'action="/tools/tags/merge' in tools
    assert 'name="source_tag_id"' in tools
    assert 'name="target_tag_id"' in tools
    assert 'Alpine.data("tagMerge"' in source
    assert "ensureDifferentTags" in source


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


def test_library_bulk_exports_hydrate_every_standard_export_preference():
    source = read("src/quirebase/assets/app.js")
    workspace = source.split('Alpine.data("libraryWorkspace"', 1)[1].split(
        'Alpine.data("importWorkspace"', 1
    )[0]

    for field in (
        "encoding",
        "journalMode",
        "doiPolicy",
        "urlPolicy",
        "excludedFields",
        "sortBy",
    ):
        assert f"{field}:" in workspace
        assert f"this.{field} = preferences.{field};" in workspace


def test_only_account_settings_mutate_saved_export_preferences():
    source = read("src/quirebase/assets/app.js")
    user_settings = source.split('Alpine.data("userSettings"', 1)[1].split(
        'Alpine.data("libraryWorkspace"', 1
    )[0]
    assert 'resetExportPreferences(this.storageKey, ["citation", "document"])' in user_settings
    assert "storeExportPreferences" in user_settings

    for component, following in (
        ("libraryWorkspace", "importWorkspace"),
        ("itemDownload", "itemExport"),
        ("itemExport", "citationStyleCatalog"),
    ):
        workspace = source.split(f'Alpine.data("{component}"', 1)[1].split(
            f'Alpine.data("{following}"', 1
        )[0]
        assert "storeExportPreferences" not in workspace
        assert "resetExportPreferences" not in workspace
        if component == "libraryWorkspace":
            assert 'this.$watch("action"' not in workspace

    assert "fetchCitationStyles(this.query, 50, this.style)" in source
    assert "this.style = this.citationStyles[0]" not in source


def test_item_export_loads_citation_styles_only_when_the_menu_is_used():
    source = read("src/quirebase/assets/app.js")
    item = read("src/quirebase/templates/item.html")
    item_export = source.split('Alpine.data("itemExport"', 1)[1]
    init = item_export.split("async loadStyles()", 1)[0]

    assert '@toggle="loadStyles()"' in item
    assert "this.searchStyles();" not in init
    assert 'if (!this.$root.open || this.format !== "csl") return;' in item_export
    assert "if (this.stylesLoaded || this.stylesLoading) return;" in item_export


def test_account_and_item_export_wire_standard_bibliography_preferences():
    source = read("src/quirebase/assets/app.js")
    settings = read("src/quirebase/templates/account_settings.html")
    item = read("src/quirebase/templates/item.html")
    user_settings = source.split('Alpine.data("userSettings"', 1)[1].split(
        'Alpine.data("libraryWorkspace"', 1
    )[0]
    item_export = source.split('Alpine.data("itemExport"', 1)[1].split(
        'Alpine.data("citationStyleCatalog"', 1
    )[0]

    assert settings.count('<option value="biblatex">BibLaTeX</option>') == 1
    assert '<option value="biblatex">BibLaTeX</option>' in item
    for field, parameter in (
        ("encoding", "encoding"),
        ("journalMode", "journal_mode"),
        ("doiPolicy", "doi_policy"),
        ("urlPolicy", "url_policy"),
        ("excludedFields", "excluded_fields"),
        ("sortBy", "sort_by"),
        ("citationKeyFormula", "citation_key_formula"),
        ("citationKeyForceAscii", "citation_key_force_ascii"),
    ):
        assert f'x-model="{field}"' in settings
        assert f"this.{field} = prefs.citation.{field};" in user_settings
        if field == "citationKeyFormula":
            assert "citationKeyFormula: this.lastValidCitationKeyFormula" in user_settings
        else:
            assert f"{field}: this.{field}" in user_settings
        assert f"this.{field} = preferences.{field};" in item_export
        assert f"{parameter}: String(this.{field})" in item_export or (
            f"{parameter}: this.{field}" in item_export
        )


def test_citation_key_formula_flows_into_every_export_surface():
    source = read("src/quirebase/assets/app.js")
    library = read("src/quirebase/templates/library.html")
    workspace = source.split('Alpine.data("libraryWorkspace"', 1)[1].split(
        'Alpine.data("importWorkspace"', 1
    )[0]

    assert 'name="citation_key_formula" :value="citationKeyFormula"' in library
    assert 'name="citation_key_force_ascii" :value="String(citationKeyForceAscii)"' in library
    assert "this.citationKeyFormula = preferences.citationKeyFormula;" in workspace
    assert "this.citationKeyForceAscii = preferences.citationKeyForceAscii;" in workspace
    assert "citation_key_force_ascii: String(this.citationKeyForceAscii)" in source


def test_account_settings_preview_citation_key_over_dedicated_endpoint():
    source = read("src/quirebase/assets/app.js")
    settings = read("src/quirebase/templates/account_settings.html")

    assert "/api/citation-key-preview" in source
    assert 'this.$watch("citationKeyFormula", () => this.previewCitationKey(true));' in source
    assert 'this.$watch("citationKeyForceAscii", () => this.previewCitationKey());' in source
    assert "this.lastValidCitationKeyFormula = formula;" in source
    assert settings.count('x-model="citationKeyFormula"') == 1
    assert 'x-text="citationKeyPreview' in settings


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
