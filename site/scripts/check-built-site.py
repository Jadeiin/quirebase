"""Check navigation, assets, anchors, and generated artifacts without a running server."""

from __future__ import annotations

import argparse
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import unquote, urljoin, urlsplit

if TYPE_CHECKING:
    from collections.abc import Mapping
    from urllib.parse import SplitResult

SITE_DIR = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


def _tag_urls(tag: str, attrs: dict[str, str | None], in_language_select: bool) -> list[str]:
    values = []
    if tag == "a":
        values.append(attrs.get("href"))
    # Canonical/alternate metadata is not a navigation or resource URL.
    if tag == "link" and attrs.get("rel") not in {"alternate", "canonical"}:
        values.append(attrs.get("href"))
    values.append(attrs.get("src"))
    if tag == "option" and in_language_select:
        values.append(attrs.get("value"))
    return [value for value in values if value]


class BuiltPage(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.urls: list[tuple[str, int]] = []
        self.in_language_select = False
        self.feed(path.read_text(encoding="utf-8"))

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if identifier := attrs.get("id"):
            self.ids.add(identifier)
        if tag == "a" and (name := attrs.get("name")):
            self.ids.add(name)
        if tag == "starlight-lang-select":
            self.in_language_select = True
        self.urls.extend(
            (value, self.getpos()[0]) for value in _tag_urls(tag, attrs, self.in_language_select)
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "starlight-lang-select":
            self.in_language_select = False


def _internal_url(origin: str, route: str, value: str) -> SplitResult | None:
    url = urlsplit(urljoin(origin + route, value))
    if url.scheme not in {"http", "https"}:
        return None
    if url.netloc != urlsplit(origin).netloc:
        return None
    return url


def _target_error(url: SplitResult, directory: Path, pages: dict[Path, BuiltPage]) -> str | None:
    target = (directory / unquote(url.path).lstrip("/")).resolve()
    if not target.is_relative_to(directory):
        return "URL escapes the site directory"
    if target.is_dir():
        target /= "index.html"
    if not target.is_file():
        return "missing page or asset"
    return _anchor_error(target, url.fragment, pages)


def _anchor_error(target: Path, fragment: str, pages: dict[Path, BuiltPage]) -> str | None:
    fragment = unquote(fragment).split(":~:text=", 1)[0]
    if not fragment:
        return None
    if target not in pages:
        return None
    if fragment not in pages[target].ids:
        return "missing anchor"
    return None


def _page_route(path: Path, directory: Path) -> str:
    relative = path.relative_to(directory).as_posix()
    return "/" + (relative.removesuffix("index.html") if path.name == "index.html" else relative)


def check_links(directory: Path, origin: str) -> tuple[list[str], int, int]:
    pages = {path: BuiltPage(path) for path in directory.rglob("*.html")}
    errors = []
    checked = 0
    for path, page in pages.items():
        relative = path.relative_to(directory).as_posix()
        route = _page_route(path, directory)
        for value, line in page.urls:
            url = _internal_url(origin, route, value)
            if url is None:
                continue
            checked += 1
            if issue := _target_error(url, directory, pages):
                errors.append(f"{relative}:{line}: {issue}: {value}")
    if not pages:
        errors.append(f"No HTML pages found in {directory}")
    return errors, len(pages), checked


def _check_operation_pages(
    directory: Path, paths: Mapping[str, Mapping[str, object]]
) -> tuple[list[str], int]:
    operations = sum(method in HTTP_METHODS for path in paths.values() for method in path)
    reference_pages = list((directory / "reference/api/operations").glob("*/index.html"))
    errors = []
    if len(reference_pages) != operations:
        errors.append(f"Expected {operations} API operation pages, found {len(reference_pages)}")
    return errors, operations


def check_artifacts(directory: Path) -> tuple[list[str], int]:
    required = (
        "index.html",
        "404.html",
        "reference/api/index.html",
        "openapi.json",
        "pagefind/pagefind.js",
        "pagefind/pagefind-entry.json",
    )
    errors = [
        f"Missing build artifact: {relative}"
        for relative in required
        if not (directory / relative).is_file()
    ]
    if errors:
        return errors, 0

    schema = json.loads((directory / "openapi.json").read_text(encoding="utf-8"))
    exported = json.loads((SITE_DIR / "public/openapi.json").read_text(encoding="utf-8"))
    if schema != exported:
        errors.append("Built OpenAPI schema differs from the current source export")
    operation_errors, operations = _check_operation_pages(directory, schema["paths"])
    errors.extend(operation_errors)
    return errors, operations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=SITE_DIR / "dist")
    directory = parser.parse_args().directory.resolve()
    origin = os.environ.get("QUIREBASE_DOCS_SITE") or "https://documentation.invalid"
    origin_url = urlsplit(origin)
    origin = f"{origin_url.scheme}://{origin_url.netloc}"

    errors, pages, urls = check_links(directory, origin)
    artifact_errors, operations = check_artifacts(directory)
    errors.extend(artifact_errors)
    if errors:
        for error in errors[:20]:
            print(error)
        print(f"Build validation failed: {len(errors)} error(s)")
        return 1
    print(
        f"Validated {pages} HTML pages, {urls} local URLs and anchors, and {operations} API operations"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
