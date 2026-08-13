from __future__ import annotations

import json

from quirebase.metadata_lookup import lookup_metadata

SAMPLES = (
    ("doi", "10.1038/s41586-020-2649-2"),
    ("doi", "10.14454/qdd3-ps68"),
    ("pmid", "31452104"),
    ("arxiv", "1706.03762"),
)

for provider, value in SAMPLES:
    parsed, record = lookup_metadata(value, provider)
    print(
        json.dumps(
            {
                "provider": parsed.provider,
                "identifier": parsed.value,
                "title": record["title"],
                "authors": record["authors"],
            },
            ensure_ascii=False,
        )
    )
