# Testing

## Fast suite

```sh
uv sync --extra dev
uv run ruff check .
uv run pytest -q -m "not oa"
```

This suite is offline and covers schema, permissions, storage, PDF coordinates and annotations, search, bibliography interchange, maintenance, migration, security and HTTP behavior. PostgreSQL search runs in CI against PostgreSQL 17 when `QUIREBASE_TEST_POSTGRES_URL` is set.

## Real open-access PDF suite

The OA corpus manifest is `tests/oa_corpus.json`. It pins three individual article PDFs from the official PMC Cloud Service by URL, byte size and SHA-256. The PDFs are not committed to the repository. Their article records identify CC BY or CC BY-NC licenses; retain attribution and do not republish the cached corpus as part of Quirebase releases.

```sh
uv run python scripts/download-oa-corpus.py
uv run pytest -q -m oa
bun run test:oa:pdfjs
```

The Python suite validates every container and checksum, extracts all text and page geometry, rasterizes every page with PyMuPDF, generates thumbnails, uploads through the authenticated HTTP endpoint, runs the durable worker, searches extracted text, checks Range/ETag delivery, creates database annotations, exports standard PDF annotations, reopens the result and proves the source hash is unchanged.

The PDF.js suite loads every page using the exact pinned browser engine, obtains each viewport, extracts text and resolves the complete drawing operator list. Together the tests currently cover 34 real article pages and more than 160,000 extracted characters.

GitHub Actions runs this suite weekly and on manual dispatch. Downloads use the PMC Cloud Service intended for automated retrieval, not automated scraping of article pages. Update a fixture only after checking its current license record and deliberately reviewing the new checksum and expected features.

Sources and policies:

- PMC Cloud Service: <https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/>
- PMC Open Access Subset: <https://pmc.ncbi.nlm.nih.gov/tools/openftlist/>
- PMC OA Web Service: <https://pmc.ncbi.nlm.nih.gov/tools/oa-service/>
