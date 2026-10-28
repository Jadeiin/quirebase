"""Check navigation, assets, anchors, and generated artifacts without a running server."""

from __future__ import annotations

import argparse
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

SITE_DIR = Path(__file__).resolve().parents[1]
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}


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
        # Check navigable links and resource URLs, rather than canonical/alternate metadata.
        if (
            tag == "a" or (tag == "link" and attrs.get("rel") not in {"alternate", "canonical"})
        ) and (href := attrs.get("href")):
            self.urls.append((href, self.getpos()[0]))
        if src := attrs.get("src"):
            self.urls.append((src, self.getpos()[0]))
        if tag == "option" and self.in_language_select and (value := attrs.get("value")):
            self.urls.append((value, self.getpos()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "starlight-lang-select":
            self.in_language_select = False


def check_links(directory: Path, origin: str) -> tuple[list[str], int, int]:
    pages = {path: BuiltPage(path) for path in directory.rglob("*.html")}
    errors = []
    checked = 0
    for path, page in pages.items():
        relative = path.relative_to(directory).as_posix()
        route = "/" + (
            relative.removesuffix("index.html") if path.name == "index.html" else relative
        )
        for value, line in page.urls:
            url = urlsplit(urljoin(origin + route, value))
            if url.scheme not in {"http", "https"} or url.netloc != urlsplit(origin).netloc:
                continue
            checked += 1
            target = (directory / unquote(url.path).lstrip("/")).resolve()
            if not target.is_relative_to(directory):
                errors.append(f"{relative}:{line}: URL escapes the site directory: {value}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{relative}:{line}: missing page or asset: {value}")
                continue
            fragment = unquote(url.fragment).split(":~:text=", 1)[0]
            if fragment and target in pages and fragment not in pages[target].ids:
                errors.append(f"{relative}:{line}: missing anchor: {value}")
    if not pages:
        errors.append(f"No HTML pages found in {directory}")
    return errors, len(pages), checked


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
    operations = sum(method in HTTP_METHODS for path in schema["paths"].values() for method in path)
    reference_pages = list((directory / "reference/api/operations").glob("*/index.html"))
    if len(reference_pages) != operations:
        errors.append(f"Expected {operations} API operation pages, found {len(reference_pages)}")
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
