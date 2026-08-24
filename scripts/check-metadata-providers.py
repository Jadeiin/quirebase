from __future__ import annotations

import json

from inquiro import ProviderRuntime

SAMPLES = (
    ("doi", "10.1038/s41586-020-2649-2"),
    ("doi", "10.14454/qdd3-ps68"),
    ("pmid", "31452104"),
    ("arxiv", "1706.03762"),
)

for provider, value in SAMPLES:
    with ProviderRuntime() as runtime:
        record = runtime.lookup(value, provider=provider)
    print(
        json.dumps(
            {
                "provider": record.identifier.provider,
                "identifier": record.identifier.value,
                "title": record.title,
                "authors": record.authors,
            },
            ensure_ascii=False,
        )
    )
