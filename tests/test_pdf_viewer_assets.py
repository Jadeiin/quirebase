from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_import(source: str, module: str) -> None:
    assert re.search(rf"\bfrom\s+(['\"]){re.escape(module)}\1", source)


def test_pdf_reader_uses_embedpdf_native_svelte_headless_components():
    viewer = read("frontend/src/lib/pdf/HeadlessPdfViewer.svelte")
    for module in (
        "@embedpdf/core/svelte",
        "@embedpdf/engines/svelte",
        "@embedpdf/plugin-document-manager/svelte",
        "@embedpdf/plugin-viewport/svelte",
        "@embedpdf/plugin-scroll/svelte",
        "@embedpdf/plugin-render/svelte",
        "@embedpdf/plugin-interaction-manager/svelte",
        "@embedpdf/plugin-selection/svelte",
        "@embedpdf/plugin-history/svelte",
        "@embedpdf/plugin-annotation/svelte",
        "@embedpdf/plugin-pan/svelte",
        "@embedpdf/plugin-rotate/svelte",
        "@embedpdf/plugin-search/svelte",
        "@embedpdf/plugin-spread/svelte",
        "@embedpdf/plugin-thumbnail/svelte",
        "@embedpdf/plugin-zoom/svelte",
    ):
        assert_import(viewer, module)
    assert "<EmbedPDF" in viewer
    assert "<DocumentContent" in viewer
    assert "<Viewport" in viewer
    assert "<Scroller" in viewer
    assert "<RenderLayer" in viewer
    assert "<GlobalPointerProvider" in viewer
    assert "<PagePointerProvider" in viewer
    assert "<SelectionLayer" in viewer
    assert "<AnnotationLayer" in viewer
    annotation = "createPluginRegistration(AnnotationPluginPackage"
    assert viewer.index("createPluginRegistration(InteractionManagerPluginPackage)") < viewer.index(
        annotation
    )
    assert viewer.index("createPluginRegistration(SelectionPluginPackage)") < viewer.index(
        annotation
    )
    assert viewer.index("createPluginRegistration(HistoryPluginPackage)") < viewer.index(annotation)


def test_pdfium_is_a_vite_managed_same_origin_asset():
    viewer = read("frontend/src/lib/pdf/HeadlessPdfViewer.svelte")
    assert_import(viewer, "@embedpdf/pdfium/pdfium.wasm?url")
    assert "usePdfiumEngine({ wasmUrl, fontFallback: null })" in viewer
    assert not (ROOT / "scripts/install-frontend.mjs").exists()
    assert not (ROOT / "scripts/build-assets.mjs").exists()


def test_pdf_requests_include_login_session_credentials():
    viewer = read("frontend/src/lib/pdf/HeadlessPdfViewer.svelte")
    assert re.search(
        r"requestOptions\s*:\s*\{\s*credentials\s*:\s*(['\"])same-origin\1\s*\}",
        viewer,
    )


def test_pdf_annotations_are_bridged_inside_the_svelte_plugin_context():
    viewer = read("frontend/src/lib/pdf/HeadlessPdfViewer.svelte")
    sync = read("frontend/src/lib/pdf/AnnotationSync.svelte")
    assert "<AnnotationSync" in viewer
    assert "useAnnotation(() => documentId)" in sync
    assert "onAnnotationEvent" in sync
    assert "/annotations" in sync
    assert "vendorFromCanonical" in sync
    assert "canonicalFromVendor" in sync


def test_pdf_annotation_replies_and_pending_writes_are_persisted():
    sync = read("frontend/src/lib/pdf/AnnotationSync.svelte")
    writes = read("frontend/src/lib/pdf/annotation-writes.ts")
    assert "persistReplyEvent" in sync
    assert "/replies" in writes
    assert re.search(r"window\.addEventListener\(\s*(['\"])beforeunload\1", sync)
    assert "writeQueue.hasPending()" in sync


def test_pdf_workspace_has_distinct_phone_information_architecture():
    component = read("frontend/src/lib/PdfWorkspace.svelte")
    assert "<Dialog.Trigger" in component
    assert "Open inspector" in component
    assert re.search(r"<Dialog\.Trigger\b[^>]*\bsm:hidden\b", component, re.DOTALL)


def test_sveltekit_csp_allows_embedpdf_worker_without_remote_scripts():
    config = read("frontend/svelte.config.js")
    assert re.search(
        r"(['\"])worker-src\1\s*:\s*\[\s*(['\"])self\2\s*,\s*(['\"])blob:\3\s*\]",
        config,
    )
    assert re.search(
        r"(['\"])script-src\1\s*:\s*\[\s*(['\"])self\2\s*,\s*(['\"])wasm-unsafe-eval\3\s*\]",
        config,
    )
