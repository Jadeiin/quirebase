from __future__ import annotations

import importlib.util
import io
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

    def check(self, paths: list[str]) -> tuple[int, str]:
        for relative in paths:
            path = self.content / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        output = io.StringIO()
        with patch("sys.argv", ["check-content.py", str(self.content)]), redirect_stdout(output):
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
        self.assertIn("Chinese manual coverage: 2/2 pages", output)

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
        self.assertIn("Chinese manual coverage: 2/2 pages", output)

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
        self.assertIn("Duplicate English page ID 'guides/setup'", output)
        self.assertIn("guides/setup.md, guides/setup.mdx", output)
        self.assertIn("Duplicate Chinese page ID 'guides/setup'", output)
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
        self.assertIn("Missing Chinese translation: zh-cn/guides/english-only", output)
        self.assertIn("Chinese page has no English counterpart: zh-cn/guides/chinese-only", output)

    def test_requires_both_entry_routes_in_each_locale(self):
        status, output = self.check(["guides/setup.md", "zh-cn/guides/setup.mdx"])
        self.assertEqual(status, 1)
        self.assertIn("Missing English entry page: /", output)
        self.assertIn("Missing English entry page: 404", output)
        self.assertIn("Missing Chinese entry page: /", output)
        self.assertIn("Missing Chinese entry page: 404", output)


if __name__ == "__main__":
    unittest.main()
