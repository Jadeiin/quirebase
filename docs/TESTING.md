# Testing

## Test seams

Runtime I/O tests run on one event loop. Database fixtures use SQLAlchemy's `AsyncEngine` and
`AsyncSession`; HTTP tests use `httpx2.AsyncClient` with Starlette's `ASGITransport`; and Inquiro
Provider contracts await the runtime and its async stream lifecycle. A test owns its session and
does not share it with concurrent tasks. Pure projections may remain ordinary synchronous test
helpers.

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

Ordinary HTTP tests construct the Web adapter with `tests/app_helpers.py`, which leaves the MCP
mount empty. MCP projection and transport tests construct the complete application explicitly.
This keeps HTTP behavior tests at their selected seam instead of regenerating the OpenAPI-derived
MCP server for every client.

Work one vertical slice at a time: one failing behavior test, the minimal implementation that
makes it pass, then the next behavior. Test names describe domain behavior rather than function
calls or collaborator interactions.

## Fast suite

```sh
uv sync
bun install --cwd frontend && bun run --cwd frontend build   # generated, not tracked
bun run --cwd frontend i18n:check   # extract PO catalogs and compile runtime messages
bun run --cwd frontend check
bun run --cwd frontend lint
bun run --cwd frontend test
uv run prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
uv run prek run --all-files
uv run pytest -q -m "not oa" -n 4 --dist loadscope
```

The frontend commands type-check Svelte and TypeScript, enforce ESLint and Prettier, and run the
Vitest suite. The hooks reject malformed YAML/TOML/JSON, large files, case-conflicting paths,
merge markers and private keys; update the uv lock; run strict Ruff checks plus formatting;
type-check production modules with mypy; enforce Conventional Commits; and run the fast tests
before pushes. This suite is offline and covers schema, permissions, storage, PDF coordinates and
annotations, Library Search and Discovery, bibliography interchange, maintenance, migration,
security and HTTP behavior. PostgreSQL Library Search runs in CI against PostgreSQL 18 when
`QUIREBASE_TEST_POSTGRES_URL` is set; the same job applies the full migration chain with
`quirebase init-db` and runs `quirebase doctor`. Tests marked `shared_postgres` take a PostgreSQL
advisory lock, so modules that mutate the configured test database stay serial even under xdist.
Dedicated PostgreSQL, S3 and real-PDF contract jobs also remain serial because they coordinate
through one external service or corpus.

## Frontend localization

The committed catalogs are `frontend/src/lib/locales/en-US/messages.po` and
`frontend/src/lib/locales/zh-CN/messages.po`. English source text is the gettext `msgid`; edit
translations only in the PO files. Runtime `messages.ts` files are generated and ignored.

Use `$t('Literal message')` for direct text. Wrap labels translated later through a variable with
`msg('Literal message')`; the extractor rejects a dynamic argument to `msg()`. After changing UI
text, run:

```sh
bun run --cwd frontend i18n:extract
bun run --cwd frontend i18n:check
```

`i18n:extract` updates and cleans the PO catalogs. `i18n:check` repeats extraction and compiles the
catalogs, using the English source message when a target translation is still empty. CI
additionally rejects catalog drift after extraction. Run
`bun run --cwd frontend i18n:template` only when a translation service needs a generated POT file;
the POT and compiled TypeScript catalogs are build artifacts. During a translation session,
`bun run --cwd frontend i18n:watch` recompiles edited PO files for the running frontend.

## Real open-access PDF suite

The OA corpus manifest is `tests/oa_corpus.json`. It pins three individual article PDFs from the official PMC Cloud Service by URL, byte size and SHA-256. The PDFs are not committed to the repository. Their article records identify CC BY or CC BY-NC licenses; retain attribution and do not republish the cached corpus as part of Quirebase releases.

```sh
uv run python scripts/download-oa-corpus.py
uv run pytest -q -m oa
```

The Python suite validates every container and checksum, extracts all text and page geometry, rasterizes every page with PyMuPDF, generates thumbnails, uploads through the authenticated HTTP endpoint, runs the durable worker, performs Library Search over extracted text, checks Range/ETag delivery, creates database annotations, exports standard PDF annotations, reopens the result and proves the source hash is unchanged.

The suite currently covers 34 real article pages and more than 160,000 extracted characters.

GitHub Actions runs this suite weekly and on manual dispatch. Downloads use the PMC Cloud Service intended for automated retrieval, not automated scraping of article pages. Update a fixture only after checking its current license record and deliberately reviewing the new checksum and expected features.

Sources and policies:

- PMC Cloud Service: <https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/>
- PMC Open Access Subset: <https://pmc.ncbi.nlm.nih.gov/tools/openftlist/>
- PMC OA Web Service: <https://pmc.ncbi.nlm.nih.gov/tools/oa-service/>
