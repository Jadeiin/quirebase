from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path(__file__).parent.parent / "src" / "quirebase"

PACKAGE_ROLES = {
    "access": "domain-policy",
    "accounts": "business",
    "audit": "business",
    "core": "infrastructure",
    "discovery": "business",
    "documents": "business",
    "library": "business",
    "operations": "business",
    "pipeline": "business",
    "projects": "business",
    "search": "outbound-adapter",
    "web": "inbound-adapter",
}

ALLOWED_PACKAGE_DEPENDENCIES = {
    "access": {"core", "models"},
    "accounts": {"audit", "core", "models"},
    "audit": {"core", "models"},
    "core": set(),
    "discovery": {
        "access",
        "audit",
        "core",
        "documents",
        "library",
        "models",
        "operations",
        "pipeline",
        "search",
    },
    "documents": {"access", "audit", "core", "models", "operations", "pipeline"},
    "library": {"access", "audit", "core", "discovery", "models", "pipeline", "search"},
    "operations": {"audit", "core", "models"},
    "pipeline": {"audit", "core", "models", "operations", "search"},
    "projects": {"access", "audit", "core", "models", "search"},
    "search": {"models"},
    "web": {
        "access",
        "accounts",
        "audit",
        "core",
        "discovery",
        "documents",
        "library",
        "models",
        "operations",
        "pipeline",
        "projects",
    },
}

BUSINESS_ROLES = {"business", "domain-policy"}
FORBIDDEN_BUSINESS_IMPORTS = ("fastapi", "mcp", "pydantic_ai", "quirebase.web")
SESSION_METHODS = {
    "add",
    "commit",
    "delete",
    "execute",
    "flush",
    "get",
    "query",
    "rollback",
    "scalar",
    "scalars",
}


def get_python_files(directory: Path) -> list[Path]:
    return list(directory.rglob("*.py"))


def imported_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def imported_quirebase_packages(package_dir: Path) -> set[str]:
    packages: set[str] = set()
    for py_file in get_python_files(package_dir):
        for module in imported_modules(py_file):
            if module == "quirebase.models":
                packages.add("models")
            elif module.startswith("quirebase."):
                packages.add(module.split(".", 2)[1])
    packages.discard(package_dir.name)
    return packages


def annotation_mentions_session(annotation: ast.expr | None, session_types: set[str]) -> bool:
    if annotation is None:
        return False
    return any(
        (isinstance(node, ast.Name) and node.id in session_types)
        or (isinstance(node, ast.Attribute) and node.attr == "Session")
        for node in ast.walk(annotation)
    )


def session_type_names(tree: ast.AST) -> set[str]:
    names = {"Session"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module != "sqlalchemy.orm":
            continue
        for alias in node.names:
            if alias.name == "Session":
                names.add(alias.asname or alias.name)
    return names


def session_variables(
    function: ast.FunctionDef | ast.AsyncFunctionDef, types: set[str]
) -> set[str]:
    variables = {
        argument.arg
        for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs)
        if annotation_mentions_session(argument.annotation, types)
    }
    if function.args.vararg and annotation_mentions_session(function.args.vararg.annotation, types):
        variables.add(function.args.vararg.arg)
    if function.args.kwarg and annotation_mentions_session(function.args.kwarg.annotation, types):
        variables.add(function.args.kwarg.arg)

    changed = True
    while changed:
        changed = False
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Name) or value.id not in variables:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in variables:
                    variables.add(target.id)
                    changed = True
    return variables


def forbidden_session_calls(
    function: ast.FunctionDef | ast.AsyncFunctionDef, types: set[str]
) -> list[ast.Call]:
    variables = session_variables(function, types)
    return [
        call
        for call in ast.walk(function)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in variables
        and call.func.attr in SESSION_METHODS
    ]


def test_every_python_package_has_an_architectural_role():
    discovered = {
        path.name
        for path in SRC_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").exists()
    }
    assert discovered == set(PACKAGE_ROLES), (
        "Update PACKAGE_ROLES and docs/architecture/modules.md when adding or removing a package: "
        f"discovered={sorted(discovered)}, classified={sorted(PACKAGE_ROLES)}"
    )


def test_package_dependencies_match_the_documented_policy():
    assert set(ALLOWED_PACKAGE_DEPENDENCIES) == set(PACKAGE_ROLES)
    for package_name in PACKAGE_ROLES:
        actual = imported_quirebase_packages(SRC_ROOT / package_name)
        disallowed = actual - ALLOWED_PACKAGE_DEPENDENCIES[package_name]
        assert not disallowed, (
            f"quirebase.{package_name} imports undocumented packages {sorted(disallowed)}; "
            "remove the dependency or document its ownership reason in "
            "docs/architecture/modules.md and ALLOWED_PACKAGE_DEPENDENCIES"
        )


def test_session_detection_follows_type_and_variable_aliases():
    tree = ast.parse(
        """
from sqlalchemy.orm import Session as DatabaseSession

def route(connection: DatabaseSession):
    persistence = connection
    persistence.commit()
"""
    )
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))
    calls = forbidden_session_calls(function, session_type_names(tree))
    assert [call.func.attr for call in calls if isinstance(call.func, ast.Attribute)] == ["commit"]


def test_business_modules_do_not_import_transport_frameworks_or_vendor_ai_sdks():
    for package_name, role in PACKAGE_ROLES.items():
        if role not in BUSINESS_ROLES:
            continue
        for py_file in get_python_files(SRC_ROOT / package_name):
            for module in imported_modules(py_file):
                assert not module.startswith(FORBIDDEN_BUSINESS_IMPORTS), (
                    f"{py_file} illegally imports transport or vendor module {module}"
                )


def test_web_layer_does_not_own_transactions_persistence_or_audit():
    for py_file in get_python_files(SRC_ROOT / "web"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        types = session_type_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "AuditEvent":
                raise AssertionError(f"{py_file} directly references AuditEvent in the Web layer")
            if isinstance(node, ast.Name) and node.id in {"LocalObjectStore", "SearchIndex"}:
                raise AssertionError(f"{py_file} directly references {node.id} in the Web layer")
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for call in forbidden_session_calls(node, types):
                assert isinstance(call.func, ast.Attribute)
                raise AssertionError(
                    f"{py_file}:{call.lineno} directly invokes SQLAlchemy Session."
                    f"{call.func.attr}() in the Web layer"
                )


def test_only_audit_module_constructs_audit_events():
    for package_name, role in PACKAGE_ROLES.items():
        if package_name == "audit" or role not in BUSINESS_ROLES:
            continue
        for py_file in get_python_files(SRC_ROOT / package_name):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "AuditEvent"
                ):
                    raise AssertionError(
                        f"{py_file} constructs AuditEvent outside the Audit Module interface"
                    )


def test_discovery_provider_modules_do_not_depend_on_orm_or_web():
    forbidden = ("sqlalchemy", "quirebase.models", "quirebase.web", "quirebase.access")
    for filename in ("lookup.py", "search.py"):
        py_file = SRC_ROOT / "discovery" / filename
        for module in imported_modules(py_file):
            assert not module.startswith(forbidden), f"{py_file} illegally imports {module}"


def test_search_adapters_do_not_depend_on_each_other():
    for adapter_name, peer_name in (("sqlite", "postgres"), ("postgres", "sqlite")):
        py_file = SRC_ROOT / "search" / f"{adapter_name}.py"
        assert f"quirebase.search.{peer_name}" not in imported_modules(py_file)


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
        "citation.py",
    ]
    for forbidden in forbidden_root_files:
        assert not (SRC_ROOT / forbidden).exists(), (
            f"Legacy root file {forbidden} still exists in src/quirebase"
        )
    assert not (SRC_ROOT / "library" / "audit.py").exists(), (
        "Audit Events belong to quirebase.audit; do not restore quirebase.library.audit"
    )
