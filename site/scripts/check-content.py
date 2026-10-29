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


def coverage_errors(english: set[Path], chinese: set[Path]) -> list[str]:
    required = {Path("index.mdx"), Path("404.md")}
    return (
        [f"Missing English entry page: {path}" for path in sorted(required - english)]
        + [f"Missing Chinese translation: zh-cn/{path}" for path in sorted(english - chinese)]
        + [
            f"Chinese page has no English counterpart: zh-cn/{path}"
            for path in sorted(chinese - english)
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=CONTENT_DIR)
    directory = parser.parse_args().directory
    english = {path for path in content_paths(directory) if path.parts[0] != "zh-cn"}
    chinese = content_paths(directory / "zh-cn")
    errors = coverage_errors(english, chinese)
    if errors:
        for error in errors:
            print(error)
        return 1
    manuals = len(english - {Path("404.md")})
    print(f"Chinese manual coverage: {manuals}/{manuals} pages; Chinese 404 page present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
