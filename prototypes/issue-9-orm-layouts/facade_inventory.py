from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "quirebase"


def exports(package: str) -> list[str]:
    tree = ast.parse((SRC / package / "__init__.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            return [item.value for item in node.value.elts if isinstance(item, ast.Constant)]
    return []


def external_imports(package: str) -> set[str]:
    used: set[str] = set()
    for path in (*SRC.rglob("*.py"), *(ROOT / "tests").rglob("*.py")):
        if path.parent == SRC / package:
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == f"quirebase.{package}":
                used.update(alias.name for alias in node.names)
    return used


for package in sorted(path.name for path in SRC.iterdir() if (path / "__init__.py").exists()):
    public = exports(package)
    used = external_imports(package)
    for name in public:
        if package == "search" and name in {"PostgreSQLSearchIndex", "SQLiteSearchIndex"}:
            category = "concrete-adapter"
        elif name in used:
            category = "caller-facing"
        elif name[:1].isupper():
            category = "result-error-or-type (review)"
        else:
            category = "internal-helper-or-unused (review)"
        print(f"{package},{name},{category}")
