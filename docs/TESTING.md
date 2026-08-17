# Testing

## Test seams

Select the seam before writing a behavior test and name it in the issue or specification. Use
the narrowest seam that proves the caller-visible behavior:

1. **Business-operation seam** — call a public business operation with real local persistence.
   Use this for permissions, validation, transactions, audit rules and state transitions.
2. **Inbound-adapter seam** — call HTTP or CLI and assert transport behavior plus outcomes
   visible through the same interface. Do not repeat business-operation cases at every adapter.
3. **Adapter-contract seam** — run the same behavioral contract against interchangeable
   adapters, such as SQLite and PostgreSQL Library Search. Mock only true external systems;
   prefer real local substitutes for databases, files and other local dependencies.
4. **End-to-end seam** — retain a small number of critical vertical workflows crossing HTTP,
   jobs, storage and search. These are tracer bullets, not the default home for every branch.

Assertions should use the seam under test. Direct database assertions are reserved for
persistence contracts or outcomes with no public query interface, such as an internal Audit
Event. A test that starts through HTTP and verifies ordinary behavior only through ORM tables is
coupled to implementation structure and should instead assert the returned page/interface or
move the behavior to a business-operation test.

Work one vertical slice at a time: one failing behavior test, the minimal implementation that
makes it pass, then the next behavior. Test names describe domain behavior rather than function
calls or collaborator interactions.

## Fast suite

```sh
uv sync
uv run prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
uv run prek run --all-files
uv run pytest -q -m "not oa"
```

The hooks reject malformed YAML/TOML/JSON, large files, case-conflicting paths, merge markers and private keys; update the uv lock; run strict Ruff checks plus formatting; type-check production modules with mypy; enforce Conventional Commits; and run the fast tests before pushes. This suite is offline and covers schema, permissions, storage, PDF coordinates and annotations, Library Search and Discovery, bibliography interchange, maintenance, migration, security and HTTP behavior. PostgreSQL Library Search runs in CI against PostgreSQL 17 when `QUIREBASE_TEST_POSTGRES_URL` is set.

## Real open-access PDF suite

The OA corpus manifest is `tests/oa_corpus.json`. It pins three individual article PDFs from the official PMC Cloud Service by URL, byte size and SHA-256. The PDFs are not committed to the repository. Their article records identify CC BY or CC BY-NC licenses; retain attribution and do not republish the cached corpus as part of Quirebase releases.

```sh
uv run python scripts/download-oa-corpus.py
uv run pytest -q -m oa
bun run test:oa:pdfjs
```

The Python suite validates every container and checksum, extracts all text and page geometry, rasterizes every page with PyMuPDF, generates thumbnails, uploads through the authenticated HTTP endpoint, runs the durable worker, performs Library Search over extracted text, checks Range/ETag delivery, creates database annotations, exports standard PDF annotations, reopens the result and proves the source hash is unchanged.

The PDF.js suite loads every page using the exact pinned browser engine, obtains each viewport, extracts text and resolves the complete drawing operator list. Together the tests currently cover 34 real article pages and more than 160,000 extracted characters.

GitHub Actions runs this suite weekly and on manual dispatch. Downloads use the PMC Cloud Service intended for automated retrieval, not automated scraping of article pages. Update a fixture only after checking its current license record and deliberately reviewing the new checksum and expected features.

Sources and policies:

- PMC Cloud Service: <https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/>
- PMC Open Access Subset: <https://pmc.ncbi.nlm.nih.gov/tools/openftlist/>
- PMC OA Web Service: <https://pmc.ncbi.nlm.nih.gov/tools/oa-service/>
