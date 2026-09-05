import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
VENDOR = ROOT / "src/quirebase/static/vendor"


def viewer_source() -> str:
    paths = (
        "src/quirebase/assets/pdf_viewer_schema.js",
        "src/quirebase/assets/pdf_annotation_adapter.js",
        "src/quirebase/assets/pdf_viewer.js",
    )
    return "\n".join((ROOT / path).read_text(encoding="utf-8") for path in paths)


def require_vendor_assets() -> None:
    if not (VENDOR / "pdfium.wasm").is_file():
        pytest.skip(
            "src/quirebase/static is a build output directory; "
            "run `bun install && bun run build` to exercise vendor asset checks"
        )


def test_pdf_viewer_container_meets_embedpdf_layout_contract():
    css = (ROOT / "src/quirebase/assets/styles.css").read_text(encoding="utf-8")
    rule = re.search(r"#embedpdf-viewer\s*\{([^}]*)\}", css)
    assert rule is not None
    declarations = rule.group(1)
    assert "position: absolute" in declarations
    assert "inset: 0" in declarations


def test_embedpdf_owns_rendering_selection_and_annotation_layers():
    template = (ROOT / "src/quirebase/templates/pdf.html").read_text(encoding="utf-8")
    script = viewer_source()
    assert 'id="embedpdf-viewer"' in template
    assert 'from "@embedpdf/snippet"' in script
    assert "selectionSegments" not in script
    assert "quirebase-overlay" not in script


def test_embedpdf_adapter_uses_offline_same_origin_configuration_and_server_truth():
    script = viewer_source()
    assert 'new URL("/static/vendor/pdfium.wasm", window.location.origin).href' in script
    assert "worker: false" not in script
    assert 'requestOptions: { credentials: "same-origin" }' in script
    assert "fontFallback: null" in script
    assert "fonts: { ui: null, signature: null }" in script
    assert "stamp: { manifests: [], defaultLibrary: false }" in script
    assert "autoCommit: false" in script
    assert "metadata = new Map()" in script
    assert "editableDocument = root.dataset.editable" in script
    assert "typeof object.custom?.text" in script
    assert "object.inReplyToId" in script
    assert "cdn.jsdelivr.net" not in script
    assert "fonts.googleapis.com" not in script


def test_embedpdf_document_loading_always_converges_to_loaded_or_localized_error():
    template = (ROOT / "src/quirebase/templates/pdf.html").read_text(encoding="utf-8")
    script = viewer_source()
    css = (ROOT / "src/quirebase/assets/styles.css").read_text(encoding="utf-8")
    assert "PDF_LOAD_TIMEOUT_MS" in script
    assert 'getPlugin("document-manager").provides()' in script
    assert "onDocumentOpened" in script
    assert "onDocumentError" in script
    assert "getDocumentState(revisionId)" in script
    assert "target.dataset.loadError" in script
    assert "'loadTimedOut': _('PDF loading timed out. Please retry or download the file.')" in template
    assert "#embedpdf-viewer[data-load-error]::after" in css


def test_embedpdf_locale_follows_the_resolved_request_locale():
    template = (ROOT / "src/quirebase/templates/pdf.html").read_text(encoding="utf-8")
    script = viewer_source()
    assert 'data-locale="{{ locale }}"' in template
    assert 'const embedPdfLocale = root.dataset.locale?.startsWith("zh") ? "zh-CN" : "en";' in script
    assert "i18n: { defaultLocale: embedPdfLocale }" in script
    assert 'defaultLocale: "zh-CN"' not in script


def test_embedpdf_adapter_normalizes_transparent_colors_for_canonical_payloads():
    script = viewer_source()
    assert (
        'const canonicalColor = (color) => color === "transparent" ? null : (color || null);'
        in script
    )
    assert "fill_color: canonicalColor(object.color || object.backgroundColor)" in script
    assert 'color: style.fill_color ?? "transparent"' in script


def test_embedpdf_toolbar_exposes_the_annotation_color_and_style_panel():
    script = viewer_source()
    assert 'commandId: "panel:toggle-annotation-style"' in script
    assert '"annotation-panel": {' in script
    assert 'componentId: "annotation-sidebar"' in script


def test_embedpdf_toolbar_restores_reader_navigation_layout_and_zoom_controls():
    schema = (ROOT / "src/quirebase/assets/pdf_viewer_schema.js").read_text(encoding="utf-8")
    assert 'commandId: "panel:toggle-sidebar"' in schema
    assert 'componentId: "thumbnails-sidebar"' in schema
    assert 'componentId: "outline-sidebar"' in schema
    assert 'commandId: "page:settings"' in schema
    for command in ("spread:none", "spread:odd", "spread:even"):
        assert f'commandId: "{command}"' in schema
    assert 'componentId: "zoom-toolbar"' in schema
    assert "[25, 50, 100, 125, 150, 200, 400, 800, 1600]" in schema
    assert "commandId: `zoom:${level}`" in schema
    assert 'commandId: "zoom:fit-page"' in schema
    assert 'commandId: "zoom:fit-width"' in schema
    assert 'commandId: "zoom:marquee"' in schema


def test_pdf_viewer_concentrates_schema_and_canonical_translation_in_modules():
    entrypoint = (ROOT / "src/quirebase/assets/pdf_viewer.js").read_text(encoding="utf-8")
    assert 'from "./pdf_viewer_schema.js"' in entrypoint
    assert 'from "./pdf_annotation_adapter.js"' in entrypoint
    assert "createAnnotationAdapter(pageGeometry)" in entrypoint
    assert "const canonicalFromVendor" not in entrypoint
    assert "const uiSchema =" not in entrypoint


def test_quirebase_controls_mount_inside_the_embedpdf_toolbar():
    template = (ROOT / "src/quirebase/templates/pdf.html").read_text(encoding="utf-8")
    script = viewer_source()
    assert 'id="pdf-toolbar-controls" hidden' in template
    assert 'id="pdf-download-options" hidden' in template
    assert "const waitForShadowElement" in script
    assert "'[data-epdf-i=\"quirebase-toolbar\"]'" in script
    assert "toolbar.append(toolbarControls);" in script
    assert "shadow.append(downloadOptions);" in script
    assert 'const downloadCurrentButton = document.querySelector("#pdf-download-current");' in script
    assert "downloadCurrentButton.addEventListener" in script
    assert "const includeAnnotations = exportAnnotations.checked" in script


def test_embedpdf_replies_use_dedicated_canonical_endpoints():
    script = viewer_source()
    assert "const replyMetadata = new Map();" in script
    assert "inReplyToId: annotation.id" in script
    assert "PdfAnnotationReplyType" in script
    assert "replyType: PdfAnnotationReplyType.Reply" in script
    assert "const parentId = event.annotation.inReplyToId;" in script
    assert "`${annotationUrl}/${parentId}/replies`" in script
    assert "vendorReplyFromCanonical(annotation, reply)" in script


def test_embedpdf_reply_creation_waits_for_the_parent_annotation_write():
    script = viewer_source()
    create_reply = script.index('if (event.type === "create")', script.index("if (parentId)"))
    wait_for_parent = script.index(
        "const pendingParentWrite = pendingWrites.get(parentId);", create_reply
    )
    post_reply = script.index("`${annotationUrl}/${parentId}/replies`", create_reply)
    assert create_reply < wait_for_parent < post_reply
    assert "if (pendingParentWrite) await pendingParentWrite;" in script


def test_embedpdf_history_create_events_restore_soft_deleted_records():
    script = viewer_source()
    assert "const annotationTombstones = new Map();" in script
    assert "const replyTombstones = new Map();" in script
    assert "annotationTombstones.set(id, { ...existing, version: existing.version + 1 });" in script
    assert "replyTombstones.set(id, { ...existing, version: existing.version + 1 });" in script
    assert "`${annotationUrl}/${id}/restore?version=${tombstone.version}`" in script
    assert (
        "`${annotationUrl}/${parentId}/replies/${id}/restore?version=${tombstone.version}`"
        in script
    )


def test_embedpdf_suppresses_reply_deletes_from_a_parent_delete_cascade():
    script = viewer_source()
    reply_delete = script.index('} else if (event.type === "delete")', script.index("if (parentId)"))
    parent_check = script.index("if (!annotationIsLoaded(parentId)) return;", reply_delete)
    delete_reply = script.index("`${annotationUrl}/${parentId}/replies/${id}", reply_delete)
    assert reply_delete < parent_check < delete_reply
    assert "for (const reply of existing.replies)" in script


def test_embedpdf_warns_before_unloading_with_pending_writes():
    script = viewer_source()
    assert 'window.addEventListener("beforeunload", (event) => {' in script
    assert "if (!pendingWrites.size) return;" in script
    assert "event.preventDefault();" in script
    assert 'event.returnValue = "";' in script


def test_embedpdf_adapter_recognizes_open_arrow_intent_and_line_ending():
    script = viewer_source()
    assert 'object.intent === "LineArrow"' in script
    assert "PdfAnnotationLineEnding.OpenArrow" in script
    assert 'PdfAnnotationLineEnding.Square]: "square"' in script
    assert 'PdfAnnotationLineEnding.ROpenArrow]: "reverse_open_arrow"' in script
    assert "payload.start_ending =" in script
    assert "payload.end_ending =" in script


def test_embedpdf_adapter_subscribes_before_plugins_finish_initializing():
    script = viewer_source()
    subscribe = "annotationApi.onAnnotationEvent(handleAnnotationEvent);"
    ready = "await registry.pluginsReady();"
    assert script.index(subscribe) < script.index(ready)
    assert "annotationApi.forDocument(documentId).getAnnotations()" in script
    assert "lockNativeAnnotations(revisionId);" in script
    assert "await initializeAnnotations();" in script


def test_embedpdf_adapter_serializes_writes_and_recovers_server_snapshots():
    script = viewer_source()
    assert "pendingWrites = new Map()" in script
    assert "const enqueue = (id, operation)" in script
    assert "await drainWrites();" in script
    assert "await recoverAnnotation(id, event.pageIndex);" in script
    assert "annotationApi.purgeAnnotation(event.pageIndex, id, revisionId);" in script


def test_new_annotation_editing_is_not_overwritten_by_the_create_response():
    script = viewer_source()
    server_sync = "annotationApi.syncAnnotationObject(id, vendorFromCanonical(saved), revisionId);"
    assert script.count(server_sync) == 1
    assert 'setActiveSidebar("right", "main", "comment-panel")' in script


def test_annotation_updates_canonicalize_the_event_patch_not_the_stale_object():
    script = viewer_source()
    assert "const updatedObject = { ...event.annotation, ...event.patch };" in script
    assert "canonicalFromVendor(updatedObject, event.pageIndex, existing)" in script


def test_application_sidebar_does_not_collide_with_pdfjs_sidebar_styles():
    base = (ROOT / "src/quirebase/templates/base.html").read_text(encoding="utf-8")
    application_css = (ROOT / "src/quirebase/assets/styles.css").read_text(encoding="utf-8")
    assert 'class="app-sidebar"' in base
    assert ".app-sidebar {" in application_css
    assert 'class="sidebar"' not in base
    assert "\n.sidebar {" not in application_css


def test_saved_sidebar_collapse_preserves_mobile_layout():
    css = (ROOT / "src/quirebase/assets/styles.css").read_text(encoding="utf-8")
    mobile_rules = css.split("@media (max-width: 640px)", 1)[1]
    assert "html.sidebar-collapsed body.app-layout" in mobile_rules
    assert "body.sidebar-collapsed.app-layout" in mobile_rules
    assert "width: min(82vw, 280px)" in mobile_rules
    assert "body.sidebar-collapsed #pdf-app { left: 0; }" in mobile_rules


def test_bundled_pdfium_wasm_uses_fixed_source_and_output_paths():
    require_vendor_assets()
    build = (ROOT / "scripts/build-assets.mjs").read_text(encoding="utf-8")
    assert "node_modules/@embedpdf/pdfium/dist/pdfium.wasm" in build
    assert "src/quirebase/static/vendor/pdfium.wasm" in build
    assert (VENDOR / "pdfium.wasm").read_bytes()[:4] == b"\x00asm"


def test_pdfjs_assets_and_dependency_are_removed():
    package = (ROOT / "package.json").read_text(encoding="utf-8")
    build = (ROOT / "scripts/build-assets.mjs").read_text(encoding="utf-8")
    assert "pdfjs-dist" not in package
    assert "pdfjs-dist" not in build
    assert not any(VENDOR.glob("pdf*.mjs"))
