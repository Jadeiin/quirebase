from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import configure_mappers

PROTOTYPE_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROTOTYPE_ROOT.parent))


def measure(module_name: str) -> dict[str, object]:
    before = set(sys.modules)
    started = time.perf_counter()
    module = importlib.import_module(module_name)
    elapsed_ms = (time.perf_counter() - started) * 1000
    configure_mappers()
    metadata = module.metadata
    scratch = PROTOTYPE_ROOT / f"PROTOTYPE-wipe-me-{module_name.rsplit('.', 2)[-2]}.sqlite"
    scratch.unlink(missing_ok=True)
    engine = create_engine(f"sqlite:///{scratch}")
    metadata.create_all(engine)
    tables = tuple(sorted(metadata.tables))
    engine.dispose()
    scratch.unlink(missing_ok=True)
    imported = set(sys.modules) - before
    return {
        "layout": module_name,
        "tables": tables,
        "import_ms": round(elapsed_ms, 3),
        "web_imported": any(name.startswith("quirebase.web") for name in imported),
        "mapping_modules": len({name for name in imported if module_name.rsplit(".", 1)[0] in name}),
    }


for result in (
    measure("issue-9-orm-layouts.capability_local.metadata"),
    measure("issue-9-orm-layouts.centralized.models"),
):
    print(result)
