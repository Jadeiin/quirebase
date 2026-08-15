from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "quirebase"


def get_python_files(directory: Path) -> list[Path]:
    return list(directory.rglob("*.py"))


def test_domain_modules_do_not_import_web():
    domain_dirs = [
        "accounts",
        "access",
        "library",
        "documents",
        "projects",
        "discovery",
        "search",
        "pipeline",
        "operations",
        "core",
    ]
    for domain_name in domain_dirs:
        domain_dir = SRC_ROOT / domain_name
        if not domain_dir.exists():
            continue
        for py_file in get_python_files(domain_dir):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        assert not alias.name.startswith("quirebase.web"), (
                            f"{py_file} illegally imports {alias.name}"
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith("quirebase.web"), (
                        f"{py_file} illegally imports from {node.module}"
                    )


def test_web_layer_does_not_own_transactions_or_audit():
    web_dir = SRC_ROOT / "web"
    for py_file in get_python_files(web_dir):
        content = py_file.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("commit", "rollback")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "db"
            ):
                raise AssertionError(
                    f"{py_file} directly invokes db.{node.func.attr}() in the Web layer"
                )
            if isinstance(node, ast.Name) and node.id == "AuditEvent":
                raise AssertionError(f"{py_file} directly references AuditEvent in the Web layer")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "db"
                and node.func.attr
                in {"add", "delete", "execute", "flush", "get", "query", "scalar", "scalars"}
            ):
                raise AssertionError(
                    f"{py_file} directly invokes db.{node.func.attr}() in the Web layer"
                )
            if isinstance(node, ast.Name) and node.id in {"LocalObjectStore", "SearchIndex"}:
                raise AssertionError(f"{py_file} directly references {node.id} in the Web layer")


def test_core_does_not_depend_on_business_modules_or_models():
    core_dir = SRC_ROOT / "core"
    forbidden = (
        "quirebase.accounts",
        "quirebase.access",
        "quirebase.discovery",
        "quirebase.documents",
        "quirebase.library",
        "quirebase.models",
        "quirebase.operations",
        "quirebase.pipeline",
        "quirebase.projects",
        "quirebase.search",
        "quirebase.web",
    )
    for py_file in get_python_files(core_dir):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                assert not module.startswith(forbidden), f"{py_file} illegally imports {module}"


def test_discovery_provider_modules_do_not_depend_on_orm_or_web():
    forbidden = ("sqlalchemy", "quirebase.models", "quirebase.web", "quirebase.access")
    for filename in ("lookup.py", "search.py"):
        py_file = SRC_ROOT / "discovery" / filename
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                assert not module.startswith(forbidden), f"{py_file} illegally imports {module}"


def test_search_adapters_do_not_depend_on_each_other():
    for adapter_name, peer_name in (("sqlite", "postgres"), ("postgres", "sqlite")):
        py_file = SRC_ROOT / "search" / f"{adapter_name}.py"
        content = py_file.read_text(encoding="utf-8")
        assert f"quirebase.search.{peer_name}" not in content


def test_no_legacy_root_files_or_shims():
    forbidden_root_files = [
        "storage.py",
        "schemas.py",
        "worker.py",
        "metadata_lookup.py",
        "maintenance.py",
        "bibliography.py",
        "security.py",
        "permissions.py",
        "app.py",
        "config.py",
        "db.py",
        "i18n.py",
        "pdf_service.py",
        "search.py",
    ]
    for forbidden in forbidden_root_files:
        assert not (SRC_ROOT / forbidden).exists(), (
            f"Legacy root file {forbidden} still exists in src/quirebase"
        )
