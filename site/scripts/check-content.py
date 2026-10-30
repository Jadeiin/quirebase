"""Require a Chinese counterpart for every handwritten public documentation page."""

from __future__ import annotations

import argparse
from pathlib import Path

CONTENT_DIR = Path(__file__).resolve().parents[1] / "src/content/docs"


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


def duplicate_errors(locale: str, routes: dict[str, list[Path]]) -> list[str]:
    return [
        f"Duplicate {locale} page ID '{route or '/'}': "
        + ", ".join(sorted(path.as_posix() for path in paths))
        for route, paths in sorted(routes.items())
        if len(paths) > 1
    ]


def coverage_errors(english: dict[str, list[Path]], chinese: dict[str, list[Path]]) -> list[str]:
    required = {"", "404"}
    return (
        duplicate_errors("English", english)
        + duplicate_errors("Chinese", chinese)
        + [
            f"Missing English entry page: {route or '/'}"
            for route in sorted(required - english.keys())
        ]
        + [
            f"Missing Chinese entry page: {route or '/'}"
            for route in sorted(required - chinese.keys())
        ]
        + [
            f"Missing Chinese translation: zh-cn/{route}"
            for route in sorted(english.keys() - chinese.keys())
        ]
        + [
            f"Chinese page has no English counterpart: zh-cn/{route}"
            for route in sorted(chinese.keys() - english.keys())
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=CONTENT_DIR)
    directory = parser.parse_args().directory
    english = page_routes({path for path in content_paths(directory) if path.parts[0] != "zh-cn"})
    chinese = page_routes(content_paths(directory / "zh-cn"))
    errors = coverage_errors(english, chinese)
    if errors:
        for error in errors:
            print(error)
        return 1
    manuals = len(english.keys() - {"404"})
    print(f"Chinese manual coverage: {manuals}/{manuals} pages; Chinese 404 page present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
