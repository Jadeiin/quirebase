from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def content_disposition(filename: str, disposition_type: str = "attachment") -> str:
    safe_name = Path(filename).name
    encoded_name = quote(safe_name)
    if encoded_name != safe_name:
        return f"{disposition_type}; filename*=utf-8''{encoded_name}"
    return f'{disposition_type}; filename="{safe_name}"'
