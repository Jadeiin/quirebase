from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_svelte_frontend_owns_the_application_build():
    package = json.loads(read("frontend/package.json"))
    assert package["dependencies"]["svelte"].startswith("^5.")
    assert "@tanstack/svelte-query" in package["dependencies"]
    assert package["dependencies"]["@skeletonlabs/skeleton"] == "5.0.1"
    assert package["dependencies"]["@skeletonlabs/skeleton-svelte"] == "5.0.1"
    assert package["devDependencies"]["tailwindcss"].startswith("^4.")


def test_development_proxy_keeps_fastapi_documentation_on_the_frontend_origin():
    vite = read("frontend/vite.config.ts")
    assert "'/docs': { target: apiOrigin }" in vite
    assert "'/openapi.json': { target: apiOrigin }" in vite


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
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/+page.svelte": "ItemOverviewSection",
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/metadata/+page.svelte": (
            "ItemMetadataSection"
        ),
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/files/+page.svelte": "ItemFilesSection",
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/organize/+page.svelte": (
            "ItemOrganizeSection"
        ),
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/annotations/+page.svelte": (
            "ItemAnnotationsSection"
        ),
        "frontend/src/routes/(app)/item/[itemId]/(workspace)/discussion/+page.svelte": (
            "ItemDiscussionSection"
        ),
        "frontend/src/routes/(app)/item/[itemId]/pdf/[revisionId]/+page.svelte": "PdfWorkspace",
        "frontend/src/routes/(app)/tools/+page.svelte": "Tools",
        "frontend/src/routes/(app)/account/+page.svelte": "Account",
        "frontend/src/routes/(app)/admin/+page.svelte": "AdminOverview",
        "frontend/src/routes/(app)/admin/users/+page.svelte": "AdminUsers",
        "frontend/src/routes/(app)/admin/projects/+page.svelte": "AdminProjects",
        "frontend/src/routes/(app)/admin/items/+page.svelte": "AdminItems",
        "frontend/src/routes/(app)/admin/audit/+page.svelte": "AdminAudit",
        "frontend/src/routes/(app)/admin/workflows/+page.svelte": "AdminWorkflows",
        "frontend/src/routes/(app)/admin/settings/+page.svelte": "AdminSettings",
        "frontend/src/routes/(app)/admin/maintenance/+page.svelte": "AdminMaintenance",
        "frontend/src/routes/(public)/invitation/[token]/+page.svelte": "Invitation",
    }
    for path, component in routes.items():
        page = read(path)
        assert f"<{component}" in page

    assert "sessionQuery" in read("frontend/src/lib/app/AppShell.svelte")
    assert "apiRequest('GET', '/session'" in read("frontend/src/lib/session.ts")


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


def test_item_workspace_uses_the_fixed_query_annotation_review_projection():
    annotations = read("frontend/src/lib/features/item/annotations/ItemAnnotationsSection.svelte")
    queries = read("frontend/src/lib/features/item/queries.ts")
    assert "itemAnnotationsReviewQuery" in annotations
    assert "'/items/{item_id}/annotations/review'" in queries
    assert "annotations.isError" in annotations


def test_project_workspace_separates_administrator_lifecycle_from_membership_actions():
    workspace = read("frontend/src/lib/features/projects/ProjectWorkspace.svelte")
    assert "const canManageLifecycle = $derived(isOwner || isAdministrator)" in workspace
    assert "const canLeave = $derived(" in workspace
    assert workspace.count("{#if canManageLifecycle}") == 2
    assert "{:else if canLeave}" in workspace
