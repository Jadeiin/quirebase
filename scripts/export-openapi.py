from __future__ import annotations

import json
import sys
from pathlib import Path

from quirebase.web.app import create_app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export-openapi.py OUTPUT")
    target = Path(sys.argv[1])
    target.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
