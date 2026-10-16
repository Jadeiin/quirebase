from __future__ import annotations

import json
from pathlib import Path

pytest_plugins = ["pytester"]


def test_report_distinguishes_executed_failed_skipped_and_unselected_cases(pytester, monkeypatch):
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    helper_dir = Path(__file__).parent
    pytester.makeconftest(
        f"import sys\nsys.path.insert(0, {str(helper_dir)!r})\n"
        'pytest_plugins = ["concurrency_plugin"]\n'
    )
    pytester.makepyfile("""
        import pytest

        @pytest.mark.concurrency_case("discussion-root-delete")
        @pytest.mark.parametrize("root", ["workspace", "project"])
        def test_race(root):
            if root == "project":
                pytest.skip("demonstrate an unexecuted schedule")
            assert False, "demonstrate a failed invariant"
    """)
    report_dir = pytester.path / "reports"
    result = pytester.runpytest_subprocess("-q", f"--concurrency-report-dir={report_dir}")
    result.assert_outcomes(failed=1, skipped=1)
    report = json.loads((report_dir / "coverage.json").read_text())
    case = next(row for row in report["cases"] if row["id"] == "discussion-root-delete")
    assert case["status"] == "failed"
    assert {row["outcome"] for row in case["runs"]} == {"failed", "skipped"}
    assert any(row["status"] == "not_run" for row in report["cases"])
    assert "test_race[workspace]" in (report_dir / "coverage.md").read_text()
