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
uv run --frozen prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
uv run --frozen prek run --all-files
uv run pytest -q -m "not oa" -n 4 --dist loadscope
```

The frontend commands type-check Svelte and TypeScript, enforce ESLint and Prettier, and run the
Vitest suite. The hooks reject malformed YAML/TOML/JSON, large files, case-conflicting paths,
merge markers and private keys; refresh the uv lock against official PyPI; run strict Ruff checks
plus formatting; type-check production modules with mypy; enforce Conventional Commits; and run the fast tests
before pushes. This suite is offline and covers schema, permissions, storage, PDF coordinates and
annotations, Library Search and Discovery, bibliography interchange, maintenance, migration,
security and HTTP behavior. PostgreSQL Library Search runs in CI against PostgreSQL 18 when
`QUIREBASE_TEST_POSTGRES_URL` is set; the same job applies the full migration chain with
`quirebase init-db` and runs `quirebase doctor`. Tests marked `shared_postgres` take a PostgreSQL
advisory lock, so modules that mutate the configured test database stay serial even under xdist.
Dedicated PostgreSQL, S3 and real-PDF contract jobs also remain serial because they coordinate
through one external service or corpus.

Local `uv sync` and `uv run` respect your user-level index configuration, including mirrors such
as TUNA, and can change the source URLs in `uv.lock`. Commits that change the root or workspace
Python manifests, `uv.toml`, or `uv.lock` trigger the `uv-lock` hook, which refreshes the lockfile
against official PyPI. If the hook updates `uv.lock`, review and stage it, then retry the commit.
Python check hooks use `uv run --frozen` so they do not rewrite the lockfile using your local
mirror settings. Frontend API generation and schema fixtures also use `--frozen` when invoking
Python through uv. Use `uv run --frozen prek ...` when running hooks manually for the same reason.

## Dependency updates

Use `git-pkgs outdated --format json` to discover new releases, including versions outside the
declared ranges. Compare candidates with the direct dependencies in the root and workspace
`pyproject.toml` files and `frontend/package.json`; Python uses PEP 440 and the frontend uses
SemVer. The output also includes transitive dependencies. Review their owning direct dependency
rather than adding application requirements just to bypass its constraints. Registry aggregation
can lag, so also check the official registry when reviewing an intentional pin.

Read release notes and change ranges deliberately before running `git-pkgs update -m uv` from
the root or `git-pkgs update -m bun` from `frontend`. These commands delegate to the package
manager and respect its declared ranges; they do not discover or authorize a range migration.
Keep shared package families aligned and review `git-pkgs diff` for the actual root locks,
excluding unrelated untracked experiments. Use `uv audit --frozen` and `bun audit` on the updated
locks; `git-pkgs vulns scan` defaults to the committed baseline.

Validate changed runtime behavior, generated schemas and models, the fast suite, frontend build
and bundle budgets. PDF upgrades also run the OA corpus; workflow/storage upgrades run durable
recovery, retention races and fresh database initialization. PostgreSQL contracts require an
isolated PostgreSQL service. Keep hook revisions aligned with the locked lint tools.

The October 2026 update retains these upstream limits; review them on each dependency cycle:

- SQLAlchemy stays below 2.1 because Advanced Alchemy 1.12 imports the removed
  `sqlalchemy.util.portable_instancemethod` and fails during model import.
- TypeScript stays on 6: SvelteKit 3.1 and svelte-check 4.7 do not support 7;
  typescript-eslint 8.72 requires TypeScript below 6.1.
- python-dateutil stays below 3 because commonmeta-py 0.312 requires it.

commonmeta-py 0.312 passes the shared-ORCID contributor-role regression that blocked 0.311.
PyMuPDF 2.0 bundles layout/LLM code. Its `pymupdf-layout` and `pymupdf4llm` requirements are
empty packages for safe pip upgrades; removing them would not shrink the bundled code.

### Dependency exclusions

The root `pyproject.toml` requires uv 0.13.5+ and scopes exclusions to exact upstream versions:

- commonmeta-py: omit unused PDF rendering/metadata, XML schema validation and legacy dependency
  chains. Preserve startup schemas and ORCID/ISNI validation with scoped Marshmallow and idutils
  overrides. WeasyPrint 69 and its known vulnerabilities are absent from the resulting lock.
- PyMuPDF: omit ONNX Runtime; Quirebase uses basic PDF operations, whose import supports running
  without the layout backend.
- KeyBERT: omit Sentence Transformers and its Torch/CUDA chain; Excerpo loads local Model2Vec.
- datamodel-code-generator: omit Black and isort; the generation script selects Ruff explicitly.

These rules remove specific dependency edges, so another package can still require a shared
dependency. Do not turn them into global bans or remove NumPy/NetworkX needed by YAKE. Upgrade
an affected upstream version without extending its scope first, inspect its imports and metadata,
then revalidate before applying exclusions to the new version. This deliberately restores the
upstream requirements until the new version has been reviewed.

Use a new environment to prove excluded packages are actually absent; an existing environment
can hide missing imports. Run the fast suite, real OA PDFs, bibliography import/export and APA
citations, plus `scripts/generate-commonmeta-models.py --check`. For the optional engine:

```sh
uv sync --frozen --extra keybert
uv run --frozen --extra keybert pytest -q packages/excerpo/tests/test_local_keybert.py
```

The contract creates a tiny local model and extracts real keywords and phrases with Hub access
disabled. CI runs it with the extra installed on Linux/Python 3.12; ordinary environments skip it.
Run `uv audit --frozen` on the resulting lock. Exclusions affect repository uv resolution and the
Docker build; they are not part of wheel dependency metadata. Standard wheel installations still
resolve the upstream dependency chains. See [Deployment](DEPLOYMENT.md).

## Frontend localization

The committed catalogs are `frontend/src/lib/locales/en-US/messages.po` and
`frontend/src/lib/locales/zh-CN/messages.po`. English source text is the gettext `msgid`; edit
translations only in the PO files. Runtime `messages.ts` files are generated and ignored.

In `.svelte` files import macros from `lingui-for-svelte/macro` and use ``$t`Literal message` ``
for direct text and ``$t`Page ${page} of ${pageCount}` `` for interpolation. Use `$plural` for a
standalone plural message; a named argument such as `$plural({ count: items.length }, options)`
preserves its ICU placeholder name. Use `<Trans>` with a nested `<Plural>` for a whole sentence
containing a plural, keeping its surrounding text in the same translation unit. `$select` and
`$selectOrdinal` are available for grammatical selections and ordinal forms. Use `ph` in string
templates when an expression needs a stable placeholder name.
Define labels translated later with ``msg`Literal message` `` and render them with `$t(descriptor)`.
In ordinary `.ts` and `.svelte.ts` files import `msg` from `@lingui/core/macro`; translate descriptors
through the `i18n` instance imported from `@lingui/core` when a string is needed outside a component.

Use `msg({ message: 'Open', context: 'action' })` and
`msg({ message: 'Open', context: 'project-participation' })` for different meanings of the same text.
Context participates in generated IDs and produces separate PO entries; `comment` is only a
translator note. Avoid assigning the same explicit ID to different meanings. Runtime IDs are
generated from message text and context, while PO `msgid` remains readable English.

The old `$t('text', values)` and `msg('text')` helper signatures are not macro syntax. Place values
in template expressions; do not attach `values` to an inline macro descriptor object. The root
layout installs the Lingui context before translated components render. After changing UI text, run:

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

For browser tests, reuse an installed Chromium by setting `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH`
to its executable before running `bun run --cwd frontend test:e2e`. For example, macOS Chromium
normally uses `/Applications/Chromium.app/Contents/MacOS/Chromium`. When running in a sandbox,
grant the test process the needed browser/localhost access before assuming another browser download
is necessary. The environment override leaves CI's default Playwright browser selection intact.

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
