from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "check_built_site", Path(__file__).resolve().parents[1] / "check-built-site.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class BuiltSiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.site = self.root / "dist"
        self.site.mkdir()

    def write(self, relative: str, content: str = "") -> Path:
        path = self.site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_accepts_unset_or_root_http_origins(self):
        for value, expected in [
            (None, "https://documentation.invalid"),
            ("", "https://documentation.invalid"),
            ("https://docs.example.org", "https://docs.example.org"),
            ("https://docs.example.org/", "https://docs.example.org"),
            ("http://127.0.0.1:4321/", "http://127.0.0.1:4321"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(CHECKER._docs_origin(value), expected)

    def test_rejects_unsupported_docs_paths_and_invalid_origins(self):
        for value in [
            "https://docs.example.org/quirebase/",
            "https://docs.example.org/guide/..",
            "https://docs.example.org/?preview=true",
            "https://docs.example.org/#guide",
            "https://reader:secret@docs.example.org/",
            "docs.example.org",
            "https:///docs.example.org",
            "file:///tmp/docs/",
            "https://docs.example.org:invalid/",
            "https://bad<host>/",
        ]:
            with (
                self.subTest(value=value),
                self.assertRaises(ValueError),
            ):
                CHECKER._docs_origin(value)

    def test_resolves_relative_root_same_host_query_and_fragment_urls(self):
        self.write("index.html", '<a href="guides/start/?from=home#intro">Start</a>')
        self.write(
            "guides/start/index.html",
            '<h1 id="intro">Start</h1>'
            '<a href="#intro">Here</a>'
            '<a href="?mode=full#intro">Query</a>'
            '<a href="../next/#result">Next</a>'
            '<a href="/guides/next/">Root</a>'
            '<a href="https://docs.example/guides/next/#result">Absolute</a>'
            '<a href="//docs.example/guides/next/">Protocol relative</a>'
            '<a href="/404.html">Missing-page guide</a>'
            '<img src="../../diagram.svg">',
        )
        self.write("guides/next/index.html", '<h2 id="result">Result</h2>')
        self.write("404.html")
        self.write("diagram.svg", "<svg/>")

        self.assertEqual(CHECKER.check_links(self.site, "https://docs.example"), ([], 4, 9))

    def test_ignores_external_and_non_http_urls(self):
        self.write(
            "index.html",
            '<a href="https://other.example/missing/">External</a>'
            '<a href="//other.example/missing/">External</a>'
            '<a href="mailto:operator@example.org">Mail</a>'
            '<a href="javascript:void(0)">Action</a>'
            '<img src="data:image/svg+xml,example">',
        )
        self.assertEqual(CHECKER.check_links(self.site, "https://docs.example"), ([], 1, 0))

    def test_reports_missing_routes_assets_and_anchors_with_source_lines(self):
        self.write(
            "index.html",
            '<a href="/missing/">Missing</a>\n'
            '<img src="/missing.svg">\n'
            '<a href="/guide/#missing">Missing anchor</a>',
        )
        self.write("guide/index.html", '<h1 id="present">Guide</h1>')

        errors, pages, urls = CHECKER.check_links(self.site, "https://docs.example")

        self.assertEqual((pages, urls), (2, 3))
        self.assertEqual(
            errors,
            [
                "index.html:1: missing page or asset: /missing/",
                "index.html:2: missing page or asset: /missing.svg",
                "index.html:3: missing anchor: /guide/#missing",
            ],
        )

    def test_decodes_paths_and_fragments_and_accepts_text_fragments(self):
        self.write(
            "index.html",
            '<a href="/guides/%E9%98%85%E8%AF%BB%20notes/#%E6%A0%87%E9%A2%98">Read</a>'
            '<a href="/guides/%E9%98%85%E8%AF%BB%20notes/#标题:~:text=example">Text</a>'
            '<a href="/guides/%E9%98%85%E8%AF%BB%20notes/#:~:text=example">Text only</a>'
            '<a href="/files/paper%23one.pdf#page=2">PDF</a>',
        )
        self.write("guides/阅读 notes/index.html", '<h1 id="标题">Read</h1>')
        self.write("files/paper#one.pdf")

        self.assertEqual(CHECKER.check_links(self.site, "https://docs.example"), ([], 2, 4))

    def test_rejects_percent_encoded_traversal(self):
        (self.root / "outside.txt").write_text("outside", encoding="utf-8")
        for url in ["/%2e%2e/outside.txt", "/..%2foutside.txt", "/%2E%2E%2Foutside.txt"]:
            with self.subTest(url=url):
                self.write("index.html", f'<a href="{url}">Outside</a>')
                errors, _, _ = CHECKER.check_links(self.site, "https://docs.example")
                self.assertEqual(errors, [f"index.html:1: URL escapes the site directory: {url}"])

    def test_rejects_symlinks_outside_the_site_including_directory_indexes(self):
        outside = self.root / "outside.html"
        outside.write_text("<h1>Outside</h1>", encoding="utf-8")
        (self.site / "file.html").symlink_to(outside)
        (self.site / "guide").mkdir()
        (self.site / "guide/index.html").symlink_to(outside)
        for url in ["/file.html", "/guide/index.html", "/guide/"]:
            with self.subTest(url=url):
                self.write("index.html", f'<a href="{url}">Outside</a>')
                errors, _, _ = CHECKER.check_links(self.site, "https://docs.example")
                self.assertEqual(errors, [f"index.html:1: URL escapes the site directory: {url}"])

    def test_checks_selected_html_url_attributes(self):
        self.write(
            "index.html",
            '<link rel="canonical" href="/metadata-only/">'
            '<link rel="alternate" href="/alternate-only/">'
            '<link rel="stylesheet" href="/missing.css">'
            '<script src="/missing.js"></script>'
            '<starlight-lang-select><select><option value="/zh-cn/">中文</option>'
            "</select></starlight-lang-select>"
            '<select><option value="/not-a-url/">Ordinary option</option></select>'
            '<img srcset="/not-inspected.png 2x">'
            "<style>body { background: url(/not-inspected.svg) }</style>",
        )
        errors, _, checked = CHECKER.check_links(self.site, "https://docs.example")
        self.assertEqual(checked, 3)
        self.assertEqual(len(errors), 3)
        for url, error in zip(["/missing.css", "/missing.js", "/zh-cn/"], errors, strict=True):
            self.assertIn(f"missing page or asset: {url}", error)

    def test_counts_only_api_http_operations_and_reports_missing_or_extra_pages(self):
        paths = {
            "/items": {"get": {}, "post": {}, "parameters": [], "summary": "Items"},
            "/other": {"$ref": "#/components/pathItems/other"},
        }
        for count in range(4):
            with self.subTest(count=count):
                if count:
                    self.write(f"reference/api/operations/op-{count}/index.html")
                errors, operations = CHECKER._check_operation_pages(self.site, paths)
                self.assertEqual(operations, 2)
                self.assertEqual(
                    errors,
                    [] if count == 2 else [f"Expected 2 API operation pages, found {count}"],
                )

    def test_artifacts_compare_the_schema_with_the_current_source_export(self):
        for relative in [
            "index.html",
            "404.html",
            "reference/api/index.html",
            "pagefind/pagefind.js",
            "pagefind/pagefind-entry.json",
        ]:
            self.write(relative)
        self.write("openapi.json", json.dumps({"paths": {"/items": {"get": {}}}}))
        source = self.root / "source/public"
        source.mkdir(parents=True)
        (source / "openapi.json").write_text('{"paths": {}}', encoding="utf-8")

        with patch.object(CHECKER, "SITE_DIR", source.parent):
            errors, operations = CHECKER.check_artifacts(self.site)

        self.assertEqual(operations, 1)
        self.assertEqual(
            errors,
            [
                "Built OpenAPI schema differs from the current source export",
                "Expected 1 API operation pages, found 0",
            ],
        )


if __name__ == "__main__":
    unittest.main()
