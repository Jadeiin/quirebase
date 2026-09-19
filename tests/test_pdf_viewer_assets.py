from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_import(source: str, module: str) -> None:
    assert re.search(rf"\bfrom\s+(['\"]){re.escape(module)}\1", source)


def test_pdf_reader_uses_embedpdf_native_svelte_headless_components():
    viewer = read("frontend/src/lib/pdf/EmbeddedPdfViewer.svelte")
    assert_import(viewer, "@embedpdf/svelte-pdf-viewer")
    assert "<PDFViewer" in viewer
    assert "AnnotationPlugin" in viewer
    assert "DocumentManagerPlugin" in viewer
    assert "UIPlugin" in viewer
    assert "CommandsPlugin" in viewer


def test_pdfium_is_a_vite_managed_same_origin_asset():
    viewer = read("frontend/src/lib/pdf/EmbeddedPdfViewer.svelte")
    assert_import(viewer, "@embedpdf/pdfium/pdfium.wasm?url")
    assert "wasmUrl: pdfiumWasmUrl" in viewer


def test_pdf_requests_include_login_session_credentials():
    viewer = read("frontend/src/lib/pdf/EmbeddedPdfViewer.svelte")
    assert re.search(
        r"requestOptions\s*:\s*\{\s*credentials\s*:\s*(['\"])same-origin\1\s*\}",
        viewer,
    )


def test_pdf_annotations_are_bridged_inside_the_svelte_plugin_context():
    viewer = read("frontend/src/lib/pdf/EmbeddedPdfViewer.svelte")
    sync = read("frontend/src/lib/pdf/annotation-sync.svelte.ts")
    adapter = read("frontend/src/lib/pdf/annotation-adapter.ts")
    assert "onAnnotationEvent" in viewer
    assert "createAnnotationSync" in viewer
    assert "/annotations" in sync
    assert "vendorFromCanonical" in adapter
    assert "canonicalFromVendor" in adapter


def test_pdf_annotation_replies_and_pending_writes_are_persisted():
    viewer = read("frontend/src/lib/pdf/EmbeddedPdfViewer.svelte")
    sync = read("frontend/src/lib/pdf/annotation-sync.svelte.ts")
    writes = read("frontend/src/lib/pdf/annotation-writes.ts")
    assert "persistReplyEvent" in sync
    assert "/replies" in writes
    assert re.search(r"window\.addEventListener\(\s*(['\"])beforeunload\1", viewer)
    assert "sync.hasPending()" in viewer
    assert "writeQueue.hasPending()" in sync


def test_pdf_workspace_has_distinct_phone_information_architecture():
    component = read("frontend/src/lib/features/pdf-reader/PdfWorkspace.svelte")
    assert "hidden sm:inline" in component
    assert "max-w-32" in component
    assert 'role="alert"' in component
    assert "EmbeddedPdfViewer" in component


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
