from __future__ import annotations

import asyncio
import json
from dataclasses import asdict

from inquiro import ProviderRuntime

SAMPLES = (
    ("doi", "10.1038/s41586-020-2649-2"),
    ("doi", "10.14454/qdd3-ps68"),
    ("pmid", "31452104"),
    ("arxiv", "1706.03762"),
)


async def main() -> None:
    for provider, value in SAMPLES:
        async with ProviderRuntime() as runtime:
            record = await runtime.lookup(value, provider=provider)
        print(
            json.dumps(
                {
                    "provider": record.provider,
                    "lookup_identifier": asdict(record.lookup_identifier),
                    "work": record.work,
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
