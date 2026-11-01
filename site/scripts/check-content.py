"""Compare public documentation routes across the configured Starlight locales."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parents[1] / "src/content/docs"
LOCALES_FILE = Path(__file__).resolve().parents[1] / "locales.json"


def content_paths(directory: Path) -> set[Path]:
    return {
        path.relative_to(directory)
        for path in directory.rglob("*")
        if path.suffix in {".md", ".mdx"}
    }


def page_routes(paths: set[Path]) -> dict[str, list[Path]]:
    routes: dict[str, list[Path]] = {}
    for path in paths:
        route = path.with_suffix("")
        if route.name == "index":
            route = route.parent
        routes.setdefault("/".join(route.parts), []).append(path)
    return routes


def locale_routes(directory: Path, locales: set[str]) -> dict[str, dict[str, list[Path]]]:
    localized = locales - {"root"}
    routes = {
        "root": page_routes({
            path for path in content_paths(directory) if path.parts[0] not in localized
        })
    }
    for locale in sorted(localized):
        routes[locale] = page_routes(content_paths(directory / locale))
    return routes


def duplicate_errors(locale: str, routes: dict[str, list[Path]]) -> list[str]:
    return [
        f"Duplicate page ID '{route or '/'}' in locale '{locale}': "
        + ", ".join(sorted(path.as_posix() for path in paths))
        for route, paths in sorted(routes.items())
        if len(paths) > 1
    ]


def entry_errors(locale: str, routes: dict[str, list[Path]]) -> list[str]:
    required = {"", "404"}
    return [
        f"Missing entry page in locale '{locale}': {route or '/'}"
        for route in sorted(required - routes.keys())
    ]


def coverage_errors(
    default: dict[str, list[Path]], translated: dict[str, list[Path]], locale: str
) -> list[str]:
    return [
        f"Missing translation in locale '{locale}': {locale}/{route}"
        for route in sorted(default.keys() - translated.keys())
    ] + [
        f"Page has no default-locale counterpart: {locale}/{route}"
        for route in sorted(translated.keys() - default.keys())
    ]


def locale_errors(routes: dict[str, dict[str, list[Path]]]) -> list[str]:
    errors = []
    for locale, pages in routes.items():
        errors.extend(duplicate_errors(locale, pages))
        errors.extend(entry_errors(locale, pages))
        if locale != "root":
            errors.extend(coverage_errors(routes["root"], pages, locale))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=CONTENT_DIR)
    directory = parser.parse_args().directory
    locales = json.loads(LOCALES_FILE.read_text(encoding="utf-8"))
    routes = locale_routes(directory, set(locales))
    errors = locale_errors(routes)
    if errors:
        print("\n".join(errors))
        return 1
    manuals = len(routes["root"].keys() - {"404"})
    print(f"Default locale ({locales['root']['lang']}): {manuals} manual routes")
    for locale in sorted(locales.keys() - {"root"}):
        print(f"Locale {locale}: {manuals}/{manuals} manual routes; 404 page present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
