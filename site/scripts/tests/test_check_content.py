from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "check_content", Path(__file__).resolve().parents[1] / "check-content.py"
)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class ContentCoverageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.content = Path(temporary.name)
        self.locales_file = self.content / "locales.json"

    def check(self, paths: list[str], locales: dict | None = None) -> tuple[int, str]:
        for relative in paths:
            path = self.content / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        self.locales_file.write_text(
            json.dumps(
                locales
                or {
                    "root": {"label": "English", "lang": "en"},
                    "zh-cn": {"label": "简体中文", "lang": "zh-CN"},
                }
            ),
            encoding="utf-8",
        )
        output = io.StringIO()
        with (
            patch("sys.argv", ["check-content.py", str(self.content)]),
            patch.object(CHECKER, "LOCALES_FILE", self.locales_file),
            redirect_stdout(output),
        ):
            status = CHECKER.main()
        return status, output.getvalue()

    def test_pairs_markdown_and_mdx_including_entry_pages(self):
        status, output = self.check([
            "index.md",
            "404.mdx",
            "guides/setup.md",
            "zh-cn/index.mdx",
            "zh-cn/404.md",
            "zh-cn/guides/setup.mdx",
        ])
        self.assertEqual(status, 0)
        self.assertIn("Default locale (en): 2 manual routes", output)
        self.assertIn("Locale zh-cn: 2/2 manual routes", output)

    def test_normalizes_directory_index_routes(self):
        status, output = self.check([
            "index.md",
            "404.md",
            "guides/setup/index.mdx",
            "zh-cn/index.md",
            "zh-cn/404.md",
            "zh-cn/guides/setup.md",
        ])
        self.assertEqual(status, 0)
        self.assertIn("Locale zh-cn: 2/2 manual routes", output)

    def test_reports_duplicate_ids_with_the_source_files_in_each_locale(self):
        status, output = self.check([
            "index.md",
            "404.md",
            "guides/setup.md",
            "guides/setup.mdx",
            "zh-cn/index.md",
            "zh-cn/404.md",
            "zh-cn/guides/setup.md",
            "zh-cn/guides/setup/index.mdx",
        ])
        self.assertEqual(status, 1)
        self.assertIn("Duplicate page ID 'guides/setup' in locale 'root'", output)
        self.assertIn("guides/setup.md, guides/setup.mdx", output)
        self.assertIn("Duplicate page ID 'guides/setup' in locale 'zh-cn'", output)
        self.assertIn("guides/setup.md, guides/setup/index.mdx", output)

    def test_reports_missing_translations_in_both_directions(self):
        status, output = self.check([
            "index.md",
            "404.md",
            "guides/english-only.mdx",
            "zh-cn/index.mdx",
            "zh-cn/404.mdx",
            "zh-cn/guides/chinese-only.md",
        ])
        self.assertEqual(status, 1)
        self.assertIn("Missing translation in locale 'zh-cn': zh-cn/guides/english-only", output)
        self.assertIn("Page has no default-locale counterpart: zh-cn/guides/chinese-only", output)

    def test_requires_both_entry_routes_in_each_locale(self):
        status, output = self.check(["guides/setup.md", "zh-cn/guides/setup.mdx"])
        self.assertEqual(status, 1)
        self.assertIn("Missing entry page in locale 'root': /", output)
        self.assertIn("Missing entry page in locale 'root': 404", output)
        self.assertIn("Missing entry page in locale 'zh-cn': /", output)
        self.assertIn("Missing entry page in locale 'zh-cn': 404", output)

    def test_validates_each_configured_locale_against_the_default_routes(self):
        locales = {
            "root": {"label": "English", "lang": "en"},
            "zh-cn": {"label": "简体中文", "lang": "zh-CN"},
            "fr": {"label": "Français", "lang": "fr"},
        }
        status, output = self.check(
            [
                "index.md",
                "404.md",
                "guides/setup.md",
                "zh-cn/index.md",
                "zh-cn/404.md",
                "zh-cn/guides/setup.mdx",
                "fr/index.mdx",
                "fr/404.md",
            ],
            locales,
        )
        self.assertEqual(status, 1)
        self.assertIn("Missing translation in locale 'fr': fr/guides/setup", output)

        status, output = self.check(["fr/guides/setup.mdx"], locales)
        self.assertEqual(status, 0)
        self.assertIn("Default locale (en): 2 manual routes", output)
        self.assertIn("Locale fr: 2/2 manual routes", output)
        self.assertIn("Locale zh-cn: 2/2 manual routes", output)

    def test_default_content_is_not_tied_to_english(self):
        status, output = self.check(
            ["index.md", "404.mdx", "guides/setup.md"],
            {"root": {"label": "Deutsch", "lang": "de"}},
        )
        self.assertEqual(status, 0)
        self.assertIn("Default locale (de): 2 manual routes", output)


if __name__ == "__main__":
    unittest.main()
