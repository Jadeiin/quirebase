from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export-openapi.py OUTPUT")

    # Schema generation must work from a clean checkout before the frontend build
    # exists. Production application startup still requires the built assets.
    os.environ["FASTAPI_ENV"] = "development"
    from quirebase.web.app import create_app

    target = Path(sys.argv[1])
    target.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
