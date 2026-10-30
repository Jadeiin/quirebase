# Quirebase documentation site

This independent Astro Starlight project contains the public user guides, concepts, administration
guides, developer integration guides, and help center. It builds static files in `site/dist/` with
Pagefind search. It does not require a running Quirebase server, initialized database, or frontend
build. Python exports the current FastAPI OpenAPI contract and validates the built artifacts.

## Work locally

From the repository root, install Python 3.12+, uv 0.13.5+, Node.js 22.23.4+, and Bun 1.4.4:

```sh
uv sync --frozen
bun install --cwd site --frozen-lockfile
bun run --cwd site dev
```

Open the local URL reported by Astro (normally `http://localhost:4321`). Each `dev`, `check`, and
`build` command exports OpenAPI through `scripts/export-openapi.py` before invoking Astro. Restart
the docs server after changing the Python API so the reference regenerates.

Before submitting a change:

```sh
bun run --cwd site test
bun run --cwd site check
bun run --cwd site build
bun run --cwd site preview
```

`check` compares source routes across configured locales and validates Astro and TypeScript.
`build` repeats the translation coverage check, validates content frontmatter, sidebar entries,
internal Markdown/MDX links and anchors, generates API Reference, and builds Pagefind indexes. It then
runs `check:build` against every generated HTML page. It reads `a[href]`, `link[href]` other than
canonical/alternate metadata, `src`, and language-selector option values. For same-host HTTP(S)
URLs, it checks that the target file or directory index exists within the build directory and that
HTML fragments match an `id` or named anchor. It also checks required entry pages, OpenAPI and
Pagefind artifact presence, compares the built OpenAPI schema with the current export, and compares
the generated operation-page count with the schema's HTTP operation count. It does not map each
operation to a particular route, inspect `srcset` or CSS URLs, or fetch resources loaded by
JavaScript. Run
`bun run --cwd site check:build` to repeat those artifact checks without rebuilding.
`test` runs focused unit tests for both Python checkers against temporary files using `unittest`.
Search is available in the built preview; Astro's development server does not build a Pagefind index.
The root Makefile also exposes `docs-dev`, `docs-check`, and `docs-build`.

## Navigation and content components

The sidebar has three topics: User guide, Administration, and Developers. Each topic shows its own
pages. The generated API Reference belongs to Developers, including its generated operation routes.
Configure topic membership and translated labels in `astro.config.mjs`.

| Extension | Purpose | Where it is used |
| --- | --- | --- |
| [starlight-sidebar-topics](https://starlight-sidebar-topics.netlify.app/docs/configuration/) | Navigation by audience | Three localized topics; generated API routes map to `developers` |
| [astro-mermaid](https://github.com/joesaby/astro-mermaid) with Mermaid | Diagrams maintained beside the prose | Localized Item/PDF/Project relationships and import workflows |
| Starlight [Tabs](https://starlight.astro.build/components/tabs/) and [Steps](https://starlight.astro.build/components/steps/) | Installation choices and sequential checks | Compose/source tabs and the first successful deployment workflow |
| starlight-openapi | Reference from the current API contract | API Reference |
| starlight-links-validator | Local link and locale validation | Every build |

Write diagrams in fenced `mermaid` blocks in Markdown. Keep them focused on one relationship or
workflow, with localized labels and explanatory prose. Mermaid renders in the browser, follows
the light/dark theme, and loads its renderer on pages containing diagrams.

Use MDX for Tabs and Steps. Keep section headings outside tab panels so the table of contents leads
to visible sections. Change both locale files when adding a diagram or changing a workflow.
When updating these extensions, preview topic switching, a generated API operation, both installation
tabs, and diagrams in light/dark themes and at a 390px viewport width.

Select extensions for a current reader or maintenance task. Image zoom becomes useful with UI
screenshots; version navigation becomes useful when several releases are supported concurrently.

## Organize content by reader and task

| Location | Owner and maintenance rule |
| --- | --- |
| `site/src/content/docs/getting-started/` | First successful user workflow |
| `site/src/content/docs/guides/` | User tasks; update alongside visible behavior changes |
| `site/src/content/docs/concepts/` | User-facing explanations using the root glossary's terms |
| `site/src/content/docs/administration/` | Operator tasks; verify commands against CLI/configuration and detailed operations contracts |
| `site/src/content/docs/developers/` | Integration and contribution workflows, linking to engineering contracts |
| `site/src/content/docs/knowledge-base/` | Questions and symptom-oriented troubleshooting with concrete recovery steps |
| `site/public/openapi.json` | Generated and ignored; never edit or commit it |
| `docs/`, `GLOSSARY.md` | Engineering contracts, accepted ADRs, agent conventions, and research; keep their existing ownership |

For operator-example validation, the minimal follow-up is a focused test that extracts literal
`quirebase` commands/options and `QUIREBASE_*` / `INQUIRO_*` keys from configured locales' administration
guides. Compare them with the existing Typer command/option metadata (`get_command(app)`) and
`Settings.model_fields`, including `env_prefix` and each field's `validation_alias`. This uses the
implementation as the registry and can validate names without executing maintenance commands.
Defaults, example values, and the sequence of operational steps still need author review.

Route paths should describe a task or concept, not a Python module. Prefer Markdown; use MDX when a
component adds value. Give every page a `title` and a useful `description`.

For an operation guide, state prerequisites and the starting screen, then give numbered steps using
the current UI labels. Explain what a successful result looks like and how to recover from a common
failure or uncertain result. Distinguish preparing work from committing it, private from shared
content, and removing a relation from deleting a resource. Check those claims against the current
UI and operation contracts. Concept pages should use a concrete example and explain the practical
consequences of the model. Link to the next task instead of repeating whole guides.

Lead with what the reader can do and the steps that achieve it. Keep role and access explanations
in the concept and member-management pages. Put input requirements beside the relevant step and
deletion consequences beside the delete action. Use concrete supported examples and brief recovery
steps, with links for readers who need more detail.

Permission guidance links to the generated
[authorization matrix](../docs/architecture/authorization-matrix.md) and the
[Workspace governance contract](../docs/architecture/workspace-governance.md). Keep exact grants in
those existing contracts rather than maintaining a second permission table in the public site.

Keep generated API route fields in FastAPI rather than duplicating parameter tables in guides. The `starlight-openapi`
plugin reads the freshly exported contract and publishes pages under `/reference/api/`; the exact
same schema is downloadable at `/openapi.json` on the documentation host.

Use root-relative, trailing-slash internal links, including anchors where helpful. Keep repository
contracts as GitHub links so they stay at their existing paths. The build checks local routes and
anchors. The generated `/reference/api/` entry point is excluded from the Markdown validator because
it is a plugin route outside the content collection; `check:build` checks its built artifact and
navigation directly. External destinations require author review. MDX components should be checked
in the built preview as well.

For a behavior change, review these questions in the same PR:

- Does a guide need a new step, changed label, permission rule, or limitation?
- Does an operator need changed configuration, migration, backup, or recovery instructions?
- Do API descriptions or examples need to change at their FastAPI source?
- Do glossary, ADR, or architecture contracts need an update independently of user-facing text?
- Are existing translations still accurate, and do the docs checks and build pass?

The repository's pull request template includes a documentation check to surface this review.

## Internationalization and localization

`locales.json` is the shared locale configuration consumed by Starlight and the coverage checker.
The `root` entry defines the default content language; other keys define locale path prefixes.
English and Simplified Chinese are currently configured. Additional locales use the same mechanism.

Every handwritten route, including the landing and 404 pages, must be present in each configured
locale. Markdown and MDX may differ by locale; route IDs omit the extension and map directory
`index` pages to their parent route. Duplicate IDs within any locale fail the coverage check.
For example, `guides/import.md` and `zh-cn/guides/import.mdx` represent the same localized route.

When adding a locale, add its entry to `locales.json`, place translated content under its path
prefix, and add UI strings in `src/content/i18n/`. Translate sidebar/topic labels in
`astro.config.mjs` and use the application's localized UI labels in task steps. Sidebar
`translations` keys and UI dictionary filenames use the configured language tag (for example
`zh-CN`), while content paths and links use the locale prefix (for example `zh-cn`).

`bun run --cwd site content:check` reports manual page coverage and fails on missing counterparts
between the default language and each configured locale. Both `check` and `build` run it. The build
also rejects untranslated fallback pages and authored links that unexpectedly switch locale. A route
pair proves presence; reviewers must still check that localized pages explain the same current behavior clearly.

Translated pages should link to the corresponding locale route, such as
`/zh-cn/guides/pdf-annotations/`. Generated API Reference remains in English and keeps its canonical
`/reference/api/` routes, with the locale selector hidden on those generated pages. Do not create
hand-maintained translations of API parameter schemas. The coverage count applies to handwritten
manuals, not generated API operation pages; localized HTTP API and MCP guides explain how to use that
reference. Update affected translations alongside the default-language page when behavior changes.

## CI and static hosting

`.github/workflows/docs.yml` installs the locked Python and site dependencies, generates the API
contract from the checked-out source, runs checker unit tests, checks the site, and builds it on
pushes and pull requests.
New runs cancel superseded documentation builds for the same Git ref.
It uploads the complete `site/dist/` directory as the `documentation-site` artifact. The documentation
build is independent of the application frontend build and release wheel.

GitHub Pages publication is planned as a separate follow-up. This change builds and uploads review
artifacts only; it does not enable Pages, change repository settings, or publish a production site.
That follow-up must configure Astro's base path for the repository's Pages URL and verify authored
links, the favicon, locale switching, API Reference, and Pagefind under that path before deployment.

For a hosting build, set `QUIREBASE_DOCS_SITE` to the actual documentation origin, for example
`https://docs.quirebase.com`, then run `bun run --cwd site build` from the repository root. This
enables canonical URLs and sitemap generation. CI reads the optional repository variable of the
same name. Leave it unset for local previews and artifacts until a deployment origin is assigned.
The configuration accepts an absolute HTTP(S) origin with an optional trailing `/`, such as
`https://docs.quirebase.com/`. Astro and `check:build` reject subpaths, credentials, query strings,
fragments, and malformed addresses. A repository Pages URL ending in `/quirebase/` needs the
separate base-path deployment work before it can be used here.
This initial setup targets the root of a dedicated documentation host; subpath hosting needs
additional base-path and link configuration.

No hosting account, application runtime, or Wiki backend is needed to build these artifacts. Add
application help links once the published documentation URL is available. Keep a single
current-version site during alpha; introduce release snapshots only when several releases are
supported concurrently.

Configuration references: [Starlight](https://starlight.astro.build/),
[internationalization](https://starlight.astro.build/guides/i18n/),
[OpenAPI plugin](https://starlight-openapi.vercel.app/getting-started/), and
[links validator](https://starlight-links-validator.vercel.app/getting-started/).
