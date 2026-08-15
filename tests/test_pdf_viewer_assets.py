import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_pdf_viewer_container_meets_pdfjs_layout_contract():
    css = (ROOT / "src/quirebase/static/app.css").read_text(encoding="utf-8")
    rule = re.search(r"#viewerContainer\s*\{([^}]*)\}", css)
    assert rule is not None
    declarations = rule.group(1)
    assert "position: absolute" in declarations
    assert "inset: 56px 0 0" in declarations


def test_pdf_pages_use_one_content_origin_for_canvas_text_and_annotations():
    template = (ROOT / "src/quirebase/templates/pdf.html").read_text(encoding="utf-8")
    script = (ROOT / "src/quirebase/static/pdf_viewer.js").read_text(encoding="utf-8")
    assert 'class="pdfViewer removePageBorders"' in template
    assert 'page.querySelector(".canvasWrapper")' in script


def test_application_sidebar_does_not_collide_with_pdfjs_sidebar_styles():
    base = (ROOT / "src/quirebase/templates/base.html").read_text(encoding="utf-8")
    application_css = (ROOT / "src/quirebase/static/app.css").read_text(encoding="utf-8")
    assert 'class="app-sidebar"' in base
    assert ".app-sidebar {" in application_css
    assert 'class="sidebar"' not in base
    assert "\n.sidebar {" not in application_css


def ensure_vendor_assets():
    vendor = ROOT / "src/quirebase/static/vendor"
    if not (vendor / "pdf.mjs").is_file():
        import shutil
        import subprocess

        bun = shutil.which("bun") or shutil.which("node")
        if bun:
            subprocess.run([bun, "scripts/build-assets.mjs"], cwd=str(ROOT), check=False)


def test_bundled_pdfjs_assets_do_not_reference_missing_source_maps():
    ensure_vendor_assets()
    vendor = ROOT / "src/quirebase/static/vendor"
    for filename in ("pdf.mjs", "pdf.worker.mjs", "pdf_viewer.mjs"):
        file_path = vendor / filename
        if file_path.is_file():
            contents = file_path.read_text(encoding="utf-8")
            assert "sourceMappingURL" not in contents


def test_pdf_viewer_stylesheet_does_not_reference_unused_image_assets():
    ensure_vendor_assets()
    vendor = ROOT / "src/quirebase/static/vendor"
    css_file = vendor / "pdf_viewer.css"
    if css_file.is_file():
        stylesheet = css_file.read_text(encoding="utf-8")
        assert not re.findall(r'url\(["\']?images/', stylesheet)
