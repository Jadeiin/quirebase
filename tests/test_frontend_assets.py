from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_svelte_frontend_owns_the_application_build():
    package = json.loads(read("frontend/package.json"))
    assert not (ROOT / "package.json").exists()
    assert package["dependencies"]["svelte"].startswith("^5.")
    assert "@tanstack/svelte-query" in package["dependencies"]
    assert package["dependencies"]["@skeletonlabs/skeleton"] == "5.0.1"
    assert package["dependencies"]["@skeletonlabs/skeleton-svelte"] == "5.0.1"
    assert "bits-ui" not in package["dependencies"]
    assert package["devDependencies"]["tailwindcss"].startswith("^4.")


def test_frontend_build_stays_outside_the_python_source_tree():
    assert (ROOT / "frontend/bun.lock").is_file()
    assert not (ROOT / "bun.lock").exists()
    assert not (ROOT / "scripts/install-frontend.mjs").exists()
    assert not any((ROOT / "src/quirebase/assets").glob("*"))
    assert not (ROOT / "src/quirebase/static").exists()


def test_wheel_and_sdist_include_generated_static_assets():
    pyproject = read("pyproject.toml")
    hook = read("scripts/hatch_build.py")
    assert 'path = "scripts/hatch_build.py"' in pyproject
    assert 'build_data["force_include"][str(frontend)] = "quirebase_frontend"' in hook
    assert 'version == "editable"' in hook
    assert 'artifacts = ["frontend/build"]' in pyproject


def test_sveltekit_filesystem_routes_own_application_navigation():
    routes = {
        "frontend/src/routes/(app)/+page.svelte": "Dashboard",
        "frontend/src/routes/(app)/library/+page.svelte": "Library",
        "frontend/src/routes/(app)/import/+page.svelte": "ImportWorkspace",
        "frontend/src/routes/(app)/discovery/+page.svelte": "Discovery",
        "frontend/src/routes/(app)/projects/+page.svelte": "Projects",
        "frontend/src/routes/(app)/projects/[projectId]/+page.svelte": "ProjectWorkspace",
        "frontend/src/routes/(app)/item/[itemId]/+page.svelte": "ItemWorkspace",
        "frontend/src/routes/(app)/item/[itemId]/[section=itemSection]/+page.svelte": "ItemWorkspace",
        "frontend/src/routes/(app)/item/[itemId]/pdf/[revisionId]/+page.svelte": "PdfWorkspace",
        "frontend/src/routes/(app)/tools/+page.svelte": "Tools",
        "frontend/src/routes/(app)/account/+page.svelte": "Account",
        "frontend/src/routes/(app)/admin/+page.svelte": "Admin",
        "frontend/src/routes/(app)/admin/[section=adminSection]/+page.svelte": "Admin",
        "frontend/src/routes/(public)/invitation/[token]/+page.svelte": "Invitation",
    }
    for path, component in routes.items():
        page = read(path)
        assert f"<{component}" in page

    assert not (ROOT / "frontend/src/routes/[...path]").exists()
    assert not (ROOT / "frontend/src/lib/App.svelte").exists()
    assert "SessionView" in read("frontend/src/lib/AppShell.svelte")
    assert "metadata" in read("frontend/src/params/itemSection.ts")
    assert "maintenance" in read("frontend/src/params/adminSection.ts")


def test_frontend_does_not_render_api_metadata_as_trusted_html():
    components = list((ROOT / "frontend/src").rglob("*.svelte"))
    raw_renderers = [
        path.relative_to(ROOT).as_posix()
        for path in components
        if "{@html" in path.read_text(encoding="utf-8")
    ]
    assert raw_renderers == ["frontend/src/lib/design/RichText.svelte"]


def test_docker_builds_the_svelte_workspace_before_the_python_wheel():
    dockerfile = read("Dockerfile")
    assert "WORKDIR /build/frontend" in dockerfile
    assert "COPY frontend/package.json frontend/bun.lock ./" in dockerfile
    assert "COPY frontend ./" in dockerfile
    assert "COPY --from=assets /build/frontend/build ./frontend/build" in dockerfile
