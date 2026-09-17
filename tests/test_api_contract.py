from __future__ import annotations

from quirebase.web.app import create_app


def test_openapi_contract_has_no_untyped_endpoints() -> None:
    """Every 2xx API route must declare an explicit, typed response schema or media-type."""
    openapi = create_app().openapi()
    paths = openapi.get("paths", {})
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
