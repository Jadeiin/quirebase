from __future__ import annotations

from app_helpers import create_web_test_app
from fastapi.routing import APIRoute

from quirebase.web.api.routes import CAPABILITY_ROUTERS, generate_operation_id
from quirebase.web.api.routes import router as api_router

OPENAPI = create_web_test_app().openapi()


def test_api_version_prefix_is_owned_by_composition_root() -> None:
    """Capability routers stay relative; only the composition root owns /api/v1."""
    assert api_router.prefix == "/api/v1"
    assert {router.prefix for router in CAPABILITY_ROUTERS} <= {"", "/admin"}
    admin_router_prefixes = [router.prefix for router in CAPABILITY_ROUTERS if router.prefix]
    assert admin_router_prefixes == ["/admin"]


def test_api_routes_have_unique_stable_operation_ids() -> None:
    """Every versioned API operation has an identifier for OpenAPI and MCP consumers."""
    paths = OPENAPI["paths"]
    operation_ids: list[str] = []

    for path, methods in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            operation_id = operation.get("operationId")
            assert isinstance(operation_id, str) and operation_id, (
                f"Missing operationId for {method.upper()} {path}"
            )
            operation_ids.append(operation_id)

    assert len(operation_ids) == len(set(operation_ids)), "Duplicate OpenAPI operation IDs"
    assert all("." in operation_id for operation_id in operation_ids)

    expected_ids = {
        generate_operation_id(route)
        for capability_router in CAPABILITY_ROUTERS
        for route in capability_router.routes
        if isinstance(route, APIRoute)
    }
    assert set(operation_ids) == expected_ids
    assert api_router.generate_unique_id_function is generate_operation_id


def test_openapi_contract_has_no_untyped_endpoints() -> None:
    """Every 2xx API route must declare an explicit, typed response schema or media-type."""
    paths = OPENAPI.get("paths", {})
    untyped: list[tuple[str, str, str, str]] = []

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            responses = operation.get("responses", {})
            for status_code, response in responses.items():
                code_str = str(status_code)
                if not code_str.startswith("2"):
                    continue
                if code_str == "204":
                    continue

                content = response.get("content", {})
                if not content:
                    untyped.append((
                        path,
                        method.upper(),
                        code_str,
                        "Missing content declaration",
                    ))
                    continue

                if "application/json" in content:
                    schema = content["application/json"].get("schema", {})
                    if not schema:
                        untyped.append((
                            path,
                            method.upper(),
                            code_str,
                            "Empty application/json schema",
                        ))

    assert not untyped, (
        f"Found {len(untyped)} untyped 2xx endpoints in OpenAPI spec:\n"
        + "\n".join(
            f"  {method} {path} ({code}): {reason}" for path, method, code, reason in untyped
        )
    )


def test_openapi_media_type_contracts() -> None:
    """Verify that multi-content-type endpoints expose all runtime media types in OpenAPI."""
    paths = OPENAPI.get("paths", {})

    bib_expected = {
        "text/plain",
        "application/x-bibtex",
        "application/x-research-info-systems",
        "application/x-endnote-refer",
    }
    for bib_path, method in [
        ("/api/v1/items/{item_id}/bibliography", "get"),
        ("/api/v1/items/bibliography", "post"),
        ("/api/v1/bibliography", "get"),
    ]:
        content = paths[bib_path][method]["responses"]["200"]["content"]
        assert set(content.keys()) == bib_expected, f"Mismatched media types in {bib_path}"

    bib_copy_content = paths["/api/v1/items/{item_id}/bibliography/content"]["get"]["responses"][
        "200"
    ]["content"]
    assert set(bib_copy_content.keys()) == {"text/plain"}

    citation_content = paths["/api/v1/items/{item_id}/citation/content"]["get"]["responses"]["200"][
        "content"
    ]
    assert set(citation_content.keys()) == {"text/plain", "text/html"}

    thumbnail_content = paths["/api/v1/items/{item_id}/thumbnail"]["get"]["responses"]["200"][
        "content"
    ]
    assert set(thumbnail_content.keys()) == {
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
    }

    attachment_content = paths["/api/v1/items/{item_id}/attachments/{attachment_id}/content"][
        "get"
    ]["responses"]["200"]["content"]
    assert set(attachment_content.keys()) == {"application/octet-stream"}


def test_openapi_api_routes_share_the_structured_error_contract() -> None:
    paths = OPENAPI["paths"]
    expected_schema = {"$ref": "#/components/schemas/ApiErrorView"}

    for path, methods in paths.items():
        if not path.startswith("/api/v1/"):
            continue
        for method, operation in methods.items():
            if method not in {"get", "post", "put", "delete", "patch"}:
                continue
            responses = operation["responses"]
            assert responses["default"]["content"]["application/json"]["schema"] == expected_schema
            assert responses["422"]["content"]["application/json"]["schema"] == expected_schema
