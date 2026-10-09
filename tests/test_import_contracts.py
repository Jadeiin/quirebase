from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SOURCE_ROOTS = ("src", "packages/inquiro/src", "packages/rubrica/src")


def lint_imports(directory: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(str(directory / root) for root in SOURCE_ROOTS)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from importlinter.cli import lint_imports_command; lint_imports_command()",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
            "--no-cache",
            "--no-logo",
        ],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_import_contracts_are_kept():
    result = lint_imports(REPO_ROOT)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    ("path", "source", "broken_contract"),
    [
        pytest.param(
            "src/quirebase/core/config.py",
            "from ..library import create_item\n",
            "Library has only documented direct callers BROKEN",
            id="relative-import",
        ),
        pytest.param(
            "src/quirebase/core/config.py",
            "from quirebase import library\n",
            "Library has only documented direct callers BROKEN",
            id="parent-package-import",
        ),
        pytest.param(
            "src/quirebase/core/config.py",
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from quirebase.library import ItemMetadata\n",
            "Library has only documented direct callers BROKEN",
            id="type-checking-import",
        ),
        pytest.param(
            "src/quirebase/web/api/imports.py",
            "from quirebase.library import imports\n",
            "Library callers use its facade; CLI registers owned workflows BROKEN",
            id="facade-bypass",
        ),
        pytest.param(
            "packages/inquiro/src/inquiro/providers/crossref.py",
            "from . import openalex\n",
            "Providers are independent leaves below their private catalog BROKEN",
            id="peer-provider-import",
        ),
        pytest.param(
            "packages/inquiro/src/inquiro/bibliography/unclassified.py",
            "VALUE = 1\n",
            "Bibliography implementation layers stay acyclic BROKEN",
            id="unclassified-bibliography-module",
        ),
        pytest.param(
            "src/quirebase/search/content.py",
            "from . import postgres\n",
            "Search adapters are independent BROKEN",
            id="indirect-search-adapter-import",
        ),
    ],
)
def test_import_contracts_reject_bypasses(
    tmp_path: Path, path: str, source: str, broken_contract: str
):
    for root in SOURCE_ROOTS:
        shutil.copytree(
            REPO_ROOT / root, tmp_path / root, ignore=shutil.ignore_patterns("__pycache__")
        )
    with (tmp_path / path).open("a", encoding="utf-8") as target:
        target.write("\n" + source)
    result = lint_imports(tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr
    assert broken_contract in result.stdout, result.stdout + result.stderr
